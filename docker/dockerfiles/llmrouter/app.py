"""OpenAI-compatible router in front of LiteLLM + request log UI.

Classifies each /v1/chat/completions request (heuristic → Haiku tiebreaker),
picks a tier (local / local-thinking / haiku / sonnet / opus), and forwards to
LiteLLM with the model field rewritten. On local-tier selection with an
unreachable Ollama, transparently promotes to a cloud tier and fires an NTFY
alert on health transitions.

Every routed request is also logged to a local SQLite DB (with an FTS5 index
over keywords + a message preview), exposed via a minimal `/ui/` web UI at the
same port.
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOG = logging.getLogger("llmrouter")

LITELLM_BASE_URL = os.environ["LITELLM_BASE_URL"].rstrip("/")
LITELLM_API_KEY = os.environ["LITELLM_API_KEY"]
ROUTER_API_KEY = os.environ["ROUTER_API_KEY"]
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://192.168.50.180:11434").rstrip("/")
NTFY_URL = os.getenv("NTFY_URL", "").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "llmrouter")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")
CLASSIFIER_MODE = os.getenv("CLASSIFIER_MODE", "hybrid")
CLASSIFIER_TIEBREAKER_MODEL = os.getenv("CLASSIFIER_TIEBREAKER_MODEL", "claude-haiku")

DB_PATH = os.getenv("LLMROUTER_DB_PATH", "/data/llmrouter.db")
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "1") not in ("0", "false", "False", "")
MESSAGES_PREVIEW_CHARS = 4000

TIER_TO_MODEL: dict[str, str] = {
    "local":          "qwen-local",
    "local-thinking": "qwen-local-thinking",
    "haiku":          "claude-haiku",
    "sonnet":         "claude-sonnet",
    "opus":           "claude-opus",
}
LOCAL_TIERS = {"local", "local-thinking"}
CLOUD_FALLBACK_TIER = "sonnet"

SECRET_KEYWORDS = (
    "password", "passwd", "api_key", "apikey", ".env", "ssh-rsa",
    "private key", "private_key", "secret", "credential", "bearer ",
)
STEP_KEYWORDS = (
    "plan ", "design ", "architect", "refactor", "debug",
    "implement", "analyze", "investigate",
)

STOPWORDS = frozenset({
    "about", "above", "after", "again", "against", "also", "another", "been",
    "before", "being", "below", "between", "both", "could", "does", "doing",
    "down", "during", "each", "every", "from", "further", "have", "having",
    "here", "itself", "just", "like", "many", "might", "more", "most", "much",
    "once", "only", "other", "over", "same", "should", "some", "such", "than",
    "that", "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "under", "until", "very", "were", "what", "when", "where",
    "which", "while", "with", "would", "your", "yours",
})

HEALTH_TTL = 5.0
_ollama_state: dict[str, Any] = {"ok": True, "checked_at": 0.0}
_ollama_lock = asyncio.Lock()

STATIC_DIR = Path(__file__).resolve().parent / "static"


# --- health + ntfy ---

async def ollama_healthy() -> bool:
    now = time.time()
    if now - _ollama_state["checked_at"] < HEALTH_TTL:
        return _ollama_state["ok"]
    async with _ollama_lock:
        if time.time() - _ollama_state["checked_at"] < HEALTH_TTL:
            return _ollama_state["ok"]
        was_ok = _ollama_state["ok"]
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{OLLAMA_URL}/api/tags")
            ok = r.status_code == 200
        except Exception as e:
            ok = False
            LOG.warning("ollama probe failed: %s", e)
        _ollama_state["ok"] = ok
        _ollama_state["checked_at"] = time.time()
        if ok != was_ok:
            asyncio.create_task(_notify_ntfy(
                title=f"Ollama {'recovered' if ok else 'unreachable'}",
                message=f"pc Ollama at {OLLAMA_URL} is now {'reachable' if ok else 'unreachable'}",
                priority="default" if ok else "high",
            ))
        return ok


async def _notify_ntfy(title: str, message: str, priority: str = "default") -> None:
    if not NTFY_URL:
        return
    headers = {"Title": title, "Priority": priority, "Tags": "robot"}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{NTFY_URL}/{NTFY_TOPIC}", content=message.encode(), headers=headers)
    except Exception as e:
        LOG.warning("ntfy send failed: %s", e)


# --- classification ---

def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(p.get("text", ""))
    return "\n".join(parts)


def heuristic_tier(body: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """First-match-wins rules. Returns (tier_or_None, signals)."""
    messages = body.get("messages", [])
    text = _messages_text(messages)
    lowered = text.lower()
    tokens = _approx_tokens(text)
    has_tools = bool(body.get("tools") or body.get("functions") or body.get("tool_choice"))
    hit_secret = next((k for k in SECRET_KEYWORDS if k in lowered), None)
    hit_step = next((k for k in STEP_KEYWORDS if k in lowered), None)
    has_code = "```" in text
    signals: dict[str, Any] = {
        "tokens": tokens,
        "has_tools": has_tools,
        "has_code": has_code,
        "has_step_word": hit_step,
        "has_secret_word": hit_secret,
    }
    if hit_secret:
        return "local-thinking", signals
    if tokens > 8000:
        return "sonnet", signals
    if has_tools:
        return "sonnet", signals
    if tokens < 200 and not has_code and not hit_step:
        return "local", signals
    if has_code or hit_step:
        return None, signals
    return "local-thinking", signals


async def haiku_tiebreaker(body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    text = _messages_text(body.get("messages", []))[:4000]
    rate_prompt = (
        "Rate the complexity of this request on a 1-5 scale. "
        "1=trivial factual, 2=simple generation, 3=moderate reasoning, "
        "4=complex multi-step, 5=deep architectural/novel. Output ONLY the digit.\n\n"
        f"---\n{text}\n---"
    )
    details: dict[str, Any] = {"prompt": rate_prompt, "response": None, "digit": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f"{LITELLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
                json={
                    "model": CLASSIFIER_TIEBREAKER_MODEL,
                    "messages": [{"role": "user", "content": rate_prompt}],
                    "max_tokens": 4,
                    "temperature": 0,
                },
            )
        content = r.json()["choices"][0]["message"]["content"]
        details["response"] = content
        digit = next((ch for ch in content if ch.isdigit()), None)
        details["digit"] = digit
        if digit is None:
            raise ValueError(f"no digit in Haiku response: {content!r}")
    except Exception as e:
        LOG.warning("tiebreaker failed, defaulting to sonnet: %s", e)
        details["error"] = str(e)
        return "sonnet", "tiebreaker-failed-default", details
    mapping = {"1": "local-thinking", "2": "local-thinking",
               "3": "sonnet", "4": "opus", "5": "opus"}
    return mapping.get(digit, "sonnet"), "haiku-tiebreaker", details


async def classify(body: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any] | None]:
    tier, signals = heuristic_tier(body)
    if tier is not None:
        return tier, "heuristic", signals, None
    if CLASSIFIER_MODE in ("hybrid", "haiku"):
        t, reason, details = await haiku_tiebreaker(body)
        return t, reason, signals, details
    return "local-thinking", "heuristic-default", signals, None


# --- storage ---

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{3,}")
_db_ready = False


def _init_db() -> None:
    global _db_ready
    if _db_ready:
        return
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                duration_ms INTEGER,
                requested_model TEXT,
                tier TEXT,
                reason TEXT,
                target_model TEXT,
                fallback_applied INTEGER DEFAULT 0,
                is_stream INTEGER DEFAULT 0,
                upstream_status INTEGER,
                approx_tokens INTEGER,
                has_tools INTEGER DEFAULT 0,
                has_code INTEGER DEFAULT 0,
                has_step_word TEXT,
                has_secret_word TEXT,
                tiebreaker_prompt TEXT,
                tiebreaker_response TEXT,
                tiebreaker_digit TEXT,
                tiebreaker_error TEXT,
                keywords TEXT,
                messages_preview TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_requests_tier ON requests(tier);

            CREATE VIRTUAL TABLE IF NOT EXISTS requests_fts USING fts5(
                keywords, messages_preview,
                content='requests', content_rowid='id',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS requests_ai AFTER INSERT ON requests BEGIN
                INSERT INTO requests_fts(rowid, keywords, messages_preview)
                VALUES (new.id, coalesce(new.keywords, ''), coalesce(new.messages_preview, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS requests_ad AFTER DELETE ON requests BEGIN
                INSERT INTO requests_fts(requests_fts, rowid, keywords, messages_preview)
                VALUES ('delete', old.id, coalesce(old.keywords, ''), coalesce(old.messages_preview, ''));
            END;
        """)
        conn.commit()
    finally:
        conn.close()
    _db_ready = True


def extract_keywords(text: str, max_n: int = 30) -> list[str]:
    freq: dict[str, int] = {}
    for w in _WORD_RE.findall(text.lower()):
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:max_n]]


def log_request(row: dict[str, Any]) -> None:
    if not LOG_REQUESTS:
        return
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
        try:
            keys = list(row.keys())
            conn.execute(
                f"INSERT INTO requests ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                [row[k] for k in keys],
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        LOG.warning("failed to log request: %s", e)


_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")


def _fts_match(q: str) -> str:
    """Turn a freeform search query into an FTS5 MATCH expression."""
    tokens = _FTS_TOKEN_RE.findall(q)
    return " ".join(f'"{t}"*' for t in tokens)


def search_requests(
    q: str = "",
    tier: str | None = None,
    since: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _init_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        where: list[str] = []
        params: list[Any] = []
        joins = ""

        match = _fts_match(q) if q else ""
        if match:
            joins = " JOIN requests_fts ON requests_fts.rowid = requests.id "
            where.append("requests_fts MATCH ?")
            params.append(match)
        if tier:
            where.append("requests.tier = ?")
            params.append(tier)
        if since is not None:
            where.append("requests.ts >= ?")
            params.append(since)
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""

        total = int(conn.execute(
            f"SELECT COUNT(*) AS n FROM requests {joins}{where_sql}", params,
        ).fetchone()["n"])

        rows = conn.execute(
            f"""SELECT requests.id, requests.ts, requests.duration_ms,
                       requests.requested_model, requests.tier, requests.reason,
                       requests.target_model, requests.fallback_applied,
                       requests.is_stream, requests.upstream_status,
                       requests.approx_tokens, requests.has_tools, requests.has_code,
                       requests.has_step_word, requests.has_secret_word,
                       requests.tiebreaker_digit, requests.keywords,
                       substr(coalesce(requests.messages_preview, ''), 1, 240) AS snippet
                FROM requests {joins}{where_sql}
                ORDER BY requests.ts DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def get_request(req_id: int) -> dict[str, Any] | None:
    _init_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def stats() -> dict[str, Any]:
    _init_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        total = int(conn.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"])
        by_tier = [
            {"tier": r["tier"], "count": r["n"]}
            for r in conn.execute(
                "SELECT tier, COUNT(*) AS n FROM requests GROUP BY tier ORDER BY n DESC"
            ).fetchall()
        ]
        by_reason = [
            {"reason": r["reason"], "count": r["n"]}
            for r in conn.execute(
                "SELECT reason, COUNT(*) AS n FROM requests GROUP BY reason ORDER BY n DESC"
            ).fetchall()
        ]
        return {"total": total, "by_tier": by_tier, "by_reason": by_reason}
    finally:
        conn.close()


# --- app ---

app = FastAPI(title="llmrouter")


@app.on_event("startup")
def _startup() -> None:
    try:
        _init_db()
    except Exception as e:
        LOG.warning("db init failed at startup: %s", e)


def _check_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if authorization[7:].strip() != ROUTER_API_KEY:
        raise HTTPException(401, "invalid api key")


@app.get("/health")
async def health() -> dict[str, Any]:
    ok = await ollama_healthy()
    return {"status": "ok", "ollama_healthy": ok}


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    now = int(time.time())
    ids = ["auto", *TIER_TO_MODEL.keys()]
    return {
        "object": "list",
        "data": [
            {"id": i, "object": "model", "created": now, "owned_by": "llmrouter"}
            for i in ids
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    _check_auth(authorization)
    body = await request.json()
    requested = body.get("model", "auto")
    t0 = time.time()

    signals: dict[str, Any] = {}
    tiebreaker: dict[str, Any] | None = None

    if requested == "auto":
        tier, reason, signals, tiebreaker = await classify(body)
    elif requested in TIER_TO_MODEL:
        tier, reason = requested, "explicit"
    else:
        tier, reason = None, "passthrough"

    fallback_applied = False
    if tier in LOCAL_TIERS and not await ollama_healthy():
        tier = CLOUD_FALLBACK_TIER
        fallback_applied = True

    target_model = TIER_TO_MODEL[tier] if tier else requested
    forward_body = {**body, "model": target_model}
    is_stream = bool(body.get("stream"))

    LOG.info(
        "route tier=%s reason=%s requested=%s target=%s stream=%s fallback=%s",
        tier, reason, requested, target_model, is_stream, fallback_applied,
    )

    response_headers = {
        "x-llmrouter-tier": str(tier),
        "x-llmrouter-reason": reason,
        "x-llmrouter-target": target_model,
    }
    if fallback_applied:
        response_headers["x-llmrouter-fallback"] = "ollama-unreachable"

    full_text = _messages_text(body.get("messages", []))
    has_secret = bool(signals.get("has_secret_word"))
    messages_preview = None if has_secret else full_text[:MESSAGES_PREVIEW_CHARS]
    keywords_list = [] if has_secret else extract_keywords(full_text)

    client = httpx.AsyncClient(timeout=None)
    upstream_req = client.build_request(
        "POST",
        f"{LITELLM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {LITELLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json=forward_body,
    )
    upstream = await client.send(upstream_req, stream=is_stream)

    base_row: dict[str, Any] = {
        "ts": t0,
        "duration_ms": None,
        "requested_model": requested,
        "tier": tier,
        "reason": reason,
        "target_model": target_model,
        "fallback_applied": 1 if fallback_applied else 0,
        "is_stream": 1 if is_stream else 0,
        "upstream_status": upstream.status_code,
        "approx_tokens": signals.get("tokens"),
        "has_tools": 1 if signals.get("has_tools") else 0,
        "has_code": 1 if signals.get("has_code") else 0,
        "has_step_word": signals.get("has_step_word"),
        "has_secret_word": signals.get("has_secret_word"),
        "tiebreaker_prompt": (tiebreaker or {}).get("prompt"),
        "tiebreaker_response": (tiebreaker or {}).get("response"),
        "tiebreaker_digit": (tiebreaker or {}).get("digit"),
        "tiebreaker_error": (tiebreaker or {}).get("error"),
        "keywords": " ".join(keywords_list) if keywords_list else None,
        "messages_preview": messages_preview,
    }

    if not is_stream:
        data = await upstream.aread()
        await client.aclose()
        base_row["duration_ms"] = int((time.time() - t0) * 1000)
        log_request(base_row)
        try:
            content = json.loads(data) if data else {}
        except json.JSONDecodeError:
            content = {"raw": data.decode("utf-8", errors="replace")}
        return JSONResponse(
            status_code=upstream.status_code,
            content=content,
            headers=response_headers,
        )

    async def iter_chunks():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
            base_row["duration_ms"] = int((time.time() - t0) * 1000)
            log_request(base_row)

    return StreamingResponse(
        iter_chunks(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
        headers=response_headers,
    )


# --- UI ---

@app.get("/", include_in_schema=False)
@app.get("/ui", include_in_schema=False)
@app.get("/ui/", include_in_schema=False)
async def ui_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/ui/api/stats")
async def ui_stats(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    return stats()


@app.get("/ui/api/requests")
async def ui_list_requests(
    q: str = Query(default=""),
    tier: str | None = Query(default=None),
    since: float | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_auth(authorization)
    return search_requests(q=q, tier=tier, since=since, limit=limit, offset=offset)


@app.get("/ui/api/requests/{req_id}")
async def ui_get_request(
    req_id: int,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_auth(authorization)
    row = get_request(req_id)
    if not row:
        raise HTTPException(404, "not found")
    return row
