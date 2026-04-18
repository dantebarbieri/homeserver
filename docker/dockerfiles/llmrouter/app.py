"""OpenAI-compatible router in front of LiteLLM.

Classifies each /v1/chat/completions request (heuristic → Haiku tiebreaker),
picks a tier (local / local-thinking / haiku / sonnet / opus), and forwards to
LiteLLM with the model field rewritten. On local-tier selection with an
unreachable Ollama, transparently promotes to a cloud tier and fires an NTFY
alert on health transitions.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

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

HEALTH_TTL = 5.0
_ollama_state: dict[str, Any] = {"ok": True, "checked_at": 0.0}
_ollama_lock = asyncio.Lock()


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


def heuristic_tier(body: dict[str, Any]) -> str | None:
    """First-match-wins rules. Returns None when ambiguous → tiebreaker needed."""
    messages = body.get("messages", [])
    text = _messages_text(messages)
    lowered = text.lower()
    tokens = _approx_tokens(text)
    has_tools = bool(body.get("tools") or body.get("functions") or body.get("tool_choice"))

    if any(k in lowered for k in SECRET_KEYWORDS):
        return "local-thinking"
    if tokens > 8000:
        return "sonnet"
    if has_tools:
        return "sonnet"
    has_code = "```" in text
    has_step = any(k in lowered for k in STEP_KEYWORDS)
    if tokens < 200 and not has_code and not has_step:
        return "local"
    if has_code or has_step:
        return None
    return "local-thinking"


async def haiku_tiebreaker(body: dict[str, Any]) -> tuple[str, str]:
    text = _messages_text(body.get("messages", []))[:4000]
    rate_prompt = (
        "Rate the complexity of this request on a 1-5 scale. "
        "1=trivial factual, 2=simple generation, 3=moderate reasoning, "
        "4=complex multi-step, 5=deep architectural/novel. Output ONLY the digit.\n\n"
        f"---\n{text}\n---"
    )
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
        digit = next((ch for ch in content if ch.isdigit()), None)
        if digit is None:
            raise ValueError(f"no digit in Haiku response: {content!r}")
    except Exception as e:
        LOG.warning("tiebreaker failed, defaulting to sonnet: %s", e)
        return "sonnet", "tiebreaker-failed-default"
    mapping = {"1": "local-thinking", "2": "local-thinking",
               "3": "sonnet", "4": "opus", "5": "opus"}
    return mapping.get(digit, "sonnet"), "haiku-tiebreaker"


async def classify(body: dict[str, Any]) -> tuple[str, str]:
    tier = heuristic_tier(body)
    if tier is not None:
        return tier, "heuristic"
    if CLASSIFIER_MODE in ("hybrid", "haiku"):
        return await haiku_tiebreaker(body)
    return "local-thinking", "heuristic-default"


app = FastAPI(title="llmrouter")


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

    if requested == "auto":
        tier, reason = await classify(body)
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

    if not is_stream:
        data = await upstream.aread()
        await client.aclose()
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

    return StreamingResponse(
        iter_chunks(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
        headers=response_headers,
    )
