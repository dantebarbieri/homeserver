"""MCP wrapper around the Travis Central Appraisal District public portal.

Backed by https://prod-container.trueprodigyapi.com (TrueProdigy SaaS, public
access). The MCP itself is bearer-auth-protected via Starlette middleware that
reads ``AUTH_TOKEN_FILE`` (or ``AUTH_TOKEN``); the upstream uses a short-lived
JWT minted on demand and cached internally.

This module is intentionally homeserver-agnostic: every external dependency
(office, upstream URL, HTTP timeout, auth token source) is pulled from the
environment so the same image can be republished on Docker Hub for any TCAD
office that runs on TrueProdigy.

Environment variables
---------------------
AUTH_TOKEN_FILE  Path to a file containing the MCP bearer token (mutually
                 exclusive with AUTH_TOKEN; one or the other is required).
AUTH_TOKEN       Bearer token as an env var (alternative to AUTH_TOKEN_FILE).
TCAD_UPSTREAM_URL  Override the TrueProdigy base URL (default the public
                   prod-container endpoint).
TCAD_OFFICE      The "office" string sent to the auth endpoint
                 (default "Travis"; e.g. "Williamson", "Hays").
TCAD_HTTP_TIMEOUT  httpx timeout in seconds (default 20).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from datetime import datetime
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UPSTREAM = os.environ.get(
    "TCAD_UPSTREAM_URL", "https://prod-container.trueprodigyapi.com"
).rstrip("/")
OFFICE = os.environ.get("TCAD_OFFICE", "Travis")
HTTP_TIMEOUT = float(os.environ.get("TCAD_HTTP_TIMEOUT", "20"))


def _load_bearer_token() -> str:
    token_file = os.environ.get("AUTH_TOKEN_FILE")
    if token_file:
        with open(token_file) as f:
            return f.read().strip()
    token = os.environ.get("AUTH_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "mcp-tcad requires AUTH_TOKEN_FILE or AUTH_TOKEN to be set"
        )
    return token


_BEARER = _load_bearer_token()


# ---------------------------------------------------------------------------
# Caches (single-process, asyncio single-threaded — no locks needed)
# ---------------------------------------------------------------------------

_token_cache: tuple[str, float] = ("", 0.0)   # (jwt, expires_at_unix_seconds)
_year_cache: tuple[int, float] = (0, 0.0)     # (year, expires_at_unix_seconds)


def _decode_jwt_exp(token: str) -> float:
    """Decode an unsigned JWT and return its ``exp`` claim (unix seconds)."""
    try:
        _header, payload, _sig = token.split(".")
        payload += "=" * (-len(payload) % 4)  # base64 padding
        body = json.loads(base64.urlsafe_b64decode(payload))
        return float(body.get("exp", time.time() + 60))
    except Exception:
        return time.time() + 60


async def _mint_token(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{UPSTREAM}/trueprodigy/cadpublic/auth/token",
        json={"office": OFFICE},
    )
    r.raise_for_status()
    return r.json()["user"]["token"]


async def _get_token(client: httpx.AsyncClient) -> str:
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at - 30:
        return token
    fresh = await _mint_token(client)
    _token_cache = (fresh, _decode_jwt_exp(fresh))
    return fresh


async def _get_year() -> int:
    """Resolve the current TCAD assessment year, with a 24h cache.

    Falls back to ``datetime.now().year`` (uncached) if the upstream call
    fails — degraded but functional.
    """
    global _year_cache
    year, expires_at = _year_cache
    if year and time.time() < expires_at:
        return year
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{UPSTREAM}/public/config/defaultyear")
            r.raise_for_status()
            new_year = int(r.json()["results"]["year"])
        _year_cache = (new_year, time.time() + 86400)
        return new_year
    except Exception:
        return datetime.now().year


async def _request(method: str, path: str, **kwargs) -> Any:
    """Authenticated upstream call. Mints a JWT if needed and retries on 401.

    Returns the parsed JSON body, or ``{}`` for HTTP 204 / empty bodies
    (TCAD uses 204 to signal "no matching rows" on the search endpoint).
    """
    global _token_cache
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        token = await _get_token(client)
        for attempt in (1, 2):
            r = await client.request(
                method,
                f"{UPSTREAM}{path}",
                headers={"Authorization": token},
                **kwargs,
            )
            if r.status_code == 401 and attempt == 1:
                _token_cache = ("", 0.0)
                token = await _get_token(client)
                continue
            r.raise_for_status()
            if r.status_code == 204 or not r.content:
                return {}
            return r.json()


# ---------------------------------------------------------------------------
# Address normalisation + fallback ladder
# ---------------------------------------------------------------------------

SUFFIX_WORDS = {
    "DR", "DRIVE", "ST", "STREET", "LN", "LANE", "AVE", "AVENUE",
    "RD", "ROAD", "CV", "COVE", "BLVD", "BOULEVARD", "CT", "COURT",
    "TRL", "TRAIL", "WAY", "PL", "PLACE", "PKWY", "PARKWAY",
    "HWY", "HIGHWAY", "CIR", "CIRCLE", "LOOP",
}


def _normalize_address(address: str) -> str:
    """Strip everything from the first comma onward, drop suffix words,
    collapse internal whitespace, uppercase. The uppercase step is purely for
    log readability — TCAD's ``mlike`` operator is case-insensitive."""
    addr = (address or "").split(",", 1)[0]
    addr = re.sub(r"\s+", " ", addr).strip().upper()
    if not addr:
        return ""
    tokens = [t for t in addr.split(" ") if t and t not in SUFFIX_WORDS]
    return " ".join(tokens)


def _build_search_ladder(normalized: str) -> list[tuple[str, str]]:
    """Return the deterministic fallback ladder of (strategy, query) pairs.

    Honours the spec exactly:
    - exact: <num> <street tokens>
    - broadened-1: drop the last street token (requires >=2 street tokens)
    - broadened-2: keep only the first street token (requires >=3)
    - street-only: drop the number entirely
    Duplicates are filtered out so we never re-issue the same query.
    """
    parts = [p for p in normalized.split(" ") if p]
    if not parts:
        return []
    has_num = parts[0].isdigit()
    num = parts[0] if has_num else ""
    street_tokens = parts[1:] if has_num else parts

    candidates: list[tuple[str, str]] = []

    def add(strategy: str, tokens: list[str], include_num: bool = True) -> None:
        if not tokens and not (include_num and num):
            return
        prefix = f"{num} " if include_num and num else ""
        query = (prefix + " ".join(tokens)).strip()
        if query:
            candidates.append((strategy, query))

    add("exact", street_tokens)
    if len(street_tokens) >= 2:
        add("broadened-1", street_tokens[:-1])
    if len(street_tokens) >= 3:
        add("broadened-2", street_tokens[:1])
    if num and street_tokens:
        add("street-only", street_tokens, include_num=False)

    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for strategy, query in candidates:
        if query in seen:
            continue
        seen.add(query)
        deduped.append((strategy, query))
    return deduped[:4]


# ---------------------------------------------------------------------------
# Field-shape helpers
# ---------------------------------------------------------------------------

def _safe_int(x: Any) -> int | None:
    if x is None or x == "":
        return None
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _safe_float(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _date_only(s: Any) -> str | None:
    """Strip the time portion of an ISO datetime, leaving just YYYY-MM-DD."""
    if not s or not isinstance(s, str):
        return s if s else None
    return s.split(" ", 1)[0].split("T", 1)[0]


def _split_subdivision(legal_description: str) -> str:
    """Strip ``LOT N BLK X`` prefix and ``SEC|UNIT|PH N`` suffix; title-case.

    e.g. ``"LOT 18 BLK T BARRINGTON OAKS SEC 3"`` -> ``"Barrington Oaks"``.
    """
    s = legal_description or ""
    s = re.sub(r"^\s*LOT\s+\S+\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*BLK\s+\S+\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+(SEC|UNIT|PH)\s+\S+\s*$", "", s, flags=re.IGNORECASE)
    return s.strip().title()


def _parse_features(raw_list: list[str]) -> tuple[dict[str, str], list[str]]:
    """Parse the free-text feature list into ``{snake_case_key: value}``."""
    parsed: dict[str, str] = {}
    raw = list(raw_list or [])
    for item in raw:
        if ": " not in item:
            continue
        key, val = item.split(": ", 1)
        snake = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if snake:
            parsed[snake] = val
    return parsed, raw


def _assemble_owner_mailing(row: dict) -> str | None:
    parts = [
        row.get("addrDeliveryLine"),
        row.get("addrUnitDesignator"),
        " ".join(
            p
            for p in (row.get("addrCity"), row.get("addrState"), row.get("addrZip"))
            if p
        ),
    ]
    joined = " ".join(p for p in parts if p).strip()
    return joined or None


def _shape_search_result(row: dict) -> dict:
    legal = row.get("legalDescription") or ""
    acreage = _safe_float(row.get("legalAcreage"))
    lot_sqft = round(acreage * 43560) if acreage is not None else None
    return {
        "pid": row.get("pid"),
        "account_id": row.get("pAccountID"),
        "subdivision": _split_subdivision(legal) or None,
        "lot_sqft": lot_sqft,
        "lot": row.get("lot"),
        "block": row.get("block"),
        "tract": row.get("tract"),
        "geo_id": row.get("geoID"),
        "map_id": row.get("mapID"),
        "tax_office_ref": row.get("taxOfficeRef"),
        "market_area": row.get("marketArea"),
        "zip": row.get("zip"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "appraised_value": _safe_int(row.get("appraisedValue")),
        "market_value": _safe_int(row.get("marketValue")),
        "land_value": _safe_int(row.get("landValue")),
        "improvement_value": _safe_int(row.get("improvementValue")),
        "zoning": row.get("zoning"),
        "legal_description": legal or None,
        "full_address": row.get("fullSitus"),
        "street_components": {
            "num": row.get("streetNum"),
            "prefix": row.get("streetPrefix"),
            "name": row.get("streetName"),
            "suffix": row.get("streetSuffix"),
            "secondary": row.get("streetSecondary"),
        },
        "owner_name": row.get("displayName") or row.get("name"),
        "owner_mailing_address": _assemble_owner_mailing(row),
        "last_deed_date": _date_only(row.get("deedDt")),
        "has_arb_hearing": (row.get("arbHearing") == "Yes"),
    }


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

mcp = FastMCP("tcad")


@mcp.tool
async def search_property(address: str, limit: int = 5) -> dict:
    """Search TCAD by address using a deterministic fallback ladder.

    The address is normalised (suffix words stripped, city/state/zip dropped)
    and searched against ``streetPrimary`` with the ``mlike`` operator. If the
    exact form returns no results, progressively broader queries are tried.

    The returned envelope tells callers which strategy hit, so anything other
    than ``strategy == "exact"`` can be flagged as a non-canonical match.

    Args:
        address: Free-text street address (e.g. ``"11301 Maidenstone Dr"``).
        limit: Maximum number of results to return.

    Returns:
        ``{strategy, query_used, totalProperty, results}``. ``strategy`` is
        one of ``"exact" | "broadened-1" | "broadened-2" | "street-only" |
        "none"``. Each entry in ``results`` is the rich shape produced by
        ``_shape_search_result`` above.
    """
    normalized = _normalize_address(address)
    ladder = _build_search_ladder(normalized)
    if not ladder:
        return {
            "strategy": "none",
            "query_used": "",
            "totalProperty": 0,
            "results": [],
        }

    year = await _get_year()
    page_size = max(int(limit), 1)
    for strategy, query in ladder:
        body = {
            "pYear": {"operator": "=", "value": str(year)},
            "streetPrimary": {"operator": "mlike", "value": query},
        }
        data = await _request(
            "POST",
            "/public/property/search",
            params={"page": 1, "pageSize": page_size},
            json=body,
        )
        rows = data.get("results") or []
        if rows:
            total = (data.get("totalProperty") or {}).get(
                "propertyCount", len(rows)
            )
            return {
                "strategy": strategy,
                "query_used": query,
                "totalProperty": total,
                "results": [_shape_search_result(r) for r in rows[:limit]],
            }
    return {
        "strategy": "none",
        "query_used": ladder[-1][1],
        "totalProperty": 0,
        "results": [],
    }


@mcp.tool
async def get_property_general(account_id: int) -> dict:
    """Fetch general property info: legal description, owner, exemptions."""
    data = await _request(
        "GET", f"/public/propertyaccount/{account_id}/general"
    )
    rows = data.get("results") or []
    if not rows:
        return {}
    r = rows[0]
    mailing = re.sub(r"\s+", " ", r.get("address") or "").strip() or None
    return {
        "pid": r.get("pID"),
        "account_id": r.get("pAccountID"),
        "assessment_year": _safe_int(r.get("pYear")),
        "legal_description": r.get("legalDescription"),
        "zoning": r.get("zoning"),
        "market_area": r.get("marketArea"),
        "market_area_description": r.get("marketAreaDescription"),
        "state_codes": r.get("stateCodes"),
        "use_code": r.get("useCd"),
        "use_code_description": r.get("useCodeDescription"),
        "owner_name": r.get("name"),
        "owner_secondary": r.get("nameSecondary"),
        "owner_pct": r.get("ownerPct"),
        "owner_mailing_address": mailing,
        "situs_address": r.get("situsAddr"),
        "street_address_short": r.get("streetAddress"),
        "exemptions": r.get("exemptionList"),
        "property_status": r.get("propertyStatus"),
        "protest_status": r.get("protestStatus"),
        # Upstream uses "informalDate" on /general but "informalDt" on /appeal.
        "informal_date": r.get("informalDate") or r.get("informalDt"),
        # Upstream typo: "formatlDate" instead of "formalDate".
        "formal_date": r.get("formatlDate") or r.get("formalDate"),
        "tax_agent": r.get("agent"),
        "tax_agent_status": r.get("agentStatus"),
        "deferral_type": r.get("deferralType"),
        "has_deferral": r.get("hasDeferral"),
        "audit_year": r.get("hsAuditYear"),
    }


@mcp.tool
async def get_property_values(account_id: int) -> dict:
    """Fetch the current value plus the (5-year) value history.

    For older history, use :func:`get_full_value_history`.
    """
    val_data, hist_data = await asyncio.gather(
        _request("GET", f"/public/propertyaccount/{account_id}/value"),
        _request("GET", f"/public/propertyaccount/{account_id}/valuehistory"),
    )
    val_rows = val_data.get("results") or []
    current: dict[str, int | None] = {}
    if val_rows:
        v = val_rows[0]
        current = {
            "land_value": _safe_int(v.get("ownerLandValue")),
            "improvement_value": _safe_int(v.get("ownerImprovementValue")),
            "market_value": _safe_int(v.get("ownerMarketValue")),
            "appraised_value": _safe_int(v.get("ownerAppraisedValue")),
            "net_appraised_value": _safe_int(v.get("ownerNetAppraisedValue")),
            "tax_limitation_value": _safe_int(v.get("ownerTaxLimitationValue")),
        }
    history: list[dict] = []
    for h in hist_data.get("results") or []:
        history.append(
            {
                "year": _safe_int(h.get("pYear")),
                "land_value": _safe_int(h.get("ownerLandValue")),
                "improvement_value": _safe_int(h.get("ownerImprovementValue")),
                "market_value": _safe_int(h.get("ownerMarketValue")),
                "appraised_value": _safe_int(h.get("ownerAppraisedValue")),
            }
        )
    history.sort(key=lambda x: x["year"] or 0)
    return {"current": current, "history": history}


@mcp.tool
async def get_full_value_history(pid: int) -> list[dict]:
    """Return one row per historical year for a given pid (pre-5-year-window).

    Uses the pid-only search trick: ``POST /public/property/search`` with no
    query string and a single ``pid`` filter returns one search-result row per
    historical year, each with its own ``pAccountID``.
    """
    body = {"pid": {"operator": "=", "value": str(pid)}}
    data = await _request("POST", "/public/property/search", json=body)
    rows = data.get("results") or []
    out = [
        {
            "year": _safe_int(r.get("pYear")),
            "account_id": r.get("pAccountID"),
            "land_value": _safe_int(r.get("landValue")),
            "improvement_value": _safe_int(r.get("improvementValue")),
            "market_value": _safe_int(r.get("marketValue")),
            "appraised_value": _safe_int(r.get("appraisedValue")),
        }
        for r in rows
    ]
    out.sort(key=lambda x: x["year"] or 0)
    return out


@mcp.tool
async def get_property_land(account_id: int) -> dict:
    """Fetch land details (size, type, market value)."""
    data = await _request("GET", f"/public/propertyaccount/{account_id}/land")
    rows = data.get("results") or []
    if not rows:
        return {}
    r = rows[0]
    return {
        "size_sqft": _safe_int(r.get("sizeSqft")),
        "size_acres": _safe_float(r.get("sizeAcres")),
        "cost_per_sqft": _safe_float(r.get("costPerSqft")),
        # Upstream renames marketValue -> mktValue on /land specifically.
        "market_value": _safe_int(r.get("mktValue")),
        "land_type": r.get("landType"),
        "land_description": r.get("landDescription"),
    }


@mcp.tool
async def get_property_improvements(account_id: int) -> dict:
    """Fetch improvement (building) details and per-component features.

    For each improvement, ``/improvement/{id}/features`` is fetched in
    parallel. The response is then collapsed into a single object: the first
    improvement's metadata (year_built, living area, etc.) at the top level,
    with components flattened across all improvements.

    ``year_built`` rule: take the minimum ``actualYearBuilt`` over components
    whose type is ``"1ST"`` or ``"2ND"`` (i.e. floor types — these reflect
    construction date). Falls back to the minimum over all components if no
    floor types exist.
    """
    imp_data = await _request(
        "GET", f"/public/propertyaccount/{account_id}/improvement"
    )
    rows = imp_data.get("results") or []
    if not rows:
        return {}
    primary = rows[0]

    feature_tasks = []
    for r in rows:
        iid = r.get("pImprovementID")
        if iid is not None:
            feature_tasks.append(
                _request(
                    "GET",
                    f"/public/propertyaccount/improvement/{iid}/features",
                )
            )
    feature_results = await asyncio.gather(*feature_tasks, return_exceptions=True)

    feat_by_detail: dict[Any, list[str]] = {}
    for fr in feature_results:
        if isinstance(fr, BaseException):
            continue
        for entry in (fr.get("results") or []):
            did = entry.get("pDetailID")
            if did is not None:
                feat_by_detail[did] = entry.get("features") or []

    components: list[dict] = []
    for r in rows:
        for d in r.get("details") or []:
            raw_features = feat_by_detail.get(d.get("pDetailID"), [])
            parsed, raw_list = _parse_features(raw_features)
            components.append(
                {
                    "detail_id": d.get("pDetailID"),
                    "type_code": d.get("imprvDetailType"),
                    "type_description": d.get("detailTypeDescription"),
                    "class": d.get("class"),
                    "area_sqft": _safe_float(d.get("area")),
                    "year_built": _safe_int(d.get("actualYearBuilt")),
                    "effective_year_built": _safe_int(d.get("effYearBuilt")),
                    "features": parsed,
                    "features_raw": raw_list,
                }
            )

    floor_years = [
        c["year_built"]
        for c in components
        if c["type_code"] in {"1ST", "2ND"} and c["year_built"]
    ]
    fallback_years = [c["year_built"] for c in components if c["year_built"]]
    year_built = (
        min(floor_years) if floor_years else (min(fallback_years) if fallback_years else None)
    )

    return {
        "year_built": year_built,
        "living_area_sqft": _safe_int(primary.get("livingArea")),
        "gross_building_area_sqft": _safe_int(primary.get("grossBuildingArea")),
        "improvement_value": _safe_int(primary.get("improvementValue")),
        "description": primary.get("imprvDescription"),
        "description_specific": primary.get("imprvSpecificDescription"),
        "state_code": primary.get("stateCd"),
        "components": components,
    }


_ISD_RE = re.compile(r"\bISD\b", re.IGNORECASE)


@mcp.tool
async def get_property_taxing_units(account_id: int) -> dict:
    """Fetch per-taxing-unit breakdown plus aggregate totals.

    ``/taxable`` returns an *object* (not a list) with both per-unit rows and
    a top-level summary. The top-level ``school_district`` field is a derived
    convenience: the ``taxingUnitName`` of the unit whose name matches
    ``\\bISD\\b`` (case-insensitive). Returns ``None`` if no ISD unit exists.
    """
    data = await _request(
        "GET", f"/public/propertyaccount/{account_id}/taxable"
    )
    blob = data.get("results") or {}
    units_raw = blob.get("taxingUnits") or []
    units: list[dict] = []
    school_district: str | None = None
    for u in units_raw:
        name = u.get("taxingUnitName")
        units.append(
            {
                "name": name,
                "code": u.get("taxingUnitCode"),
                "tax_rate": _safe_float(u.get("totalTaxRate")),
                "taxable_value": _safe_int(u.get("taxableValue")),
                "net_appraised_value": _safe_int(u.get("netAppraisedValue")),
                "estimated_taxes": _safe_float(u.get("estimatedTaxes")),
                "estimated_taxes_without_exemptions": _safe_float(
                    u.get("estimatedTaxesWoutExemptions")
                ),
                "arb_status": u.get("arbStatus"),
            }
        )
        if school_district is None and name and _ISD_RE.search(name):
            school_district = name
    return {
        "units": units,
        "total_tax_rate": _safe_float(blob.get("totalTaxRate")),
        "total_estimated_taxes": _safe_float(blob.get("estimatedTaxes")),
        "total_estimated_taxes_without_exemptions": _safe_float(
            blob.get("estimatedTaxesWoutExemptions")
        ),
        "school_district": school_district,
    }


@mcp.tool
async def get_protest_information(account_id: int) -> dict:
    """Fetch protest/appeal status for a property account."""
    data = await _request(
        "GET", f"/public/propertyaccount/{account_id}/appeal"
    )
    rows = data.get("results") or []
    if not rows:
        return {}
    r = rows[0]
    return {
        "appeal_id": r.get("appealID"),
        "appeal_type": r.get("appealType"),
        "appeal_status": r.get("appealStatus"),
        "informal_date": r.get("informalDt"),
        "docket_date": r.get("docketDt"),
        "claimant_opinion_of_value": r.get("claimantOpinionOfValue"),
        "initial_market_value": r.get("initialMarketValue"),
        "final_market_value": r.get("finalMarketValue"),
        "board_determination": r.get("boardDetermination"),
        "panel_members": r.get("panelMembers") or [],
    }


@mcp.tool
async def get_property_deed_history(pid: int) -> list[dict]:
    """Fetch full deed/sale history for a pid, sorted ascending by deed date."""
    data = await _request("GET", f"/public/property/{pid}/deeds")
    rows = data.get("results") or []
    out = [
        {
            "deed_id": r.get("deedID"),
            "deed_type": r.get("deedType"),
            "deed_description": r.get("deedDescription"),
            "deed_date": _date_only(r.get("deedDt")),
            "seller": r.get("seller"),
            "buyer": r.get("buyer"),
            "instrument_num": r.get("instrumentNum"),
            "volume": r.get("volume"),
            "book": r.get("book"),
            "page": r.get("page"),
        }
        for r in rows
    ]
    out.sort(key=lambda x: x["deed_date"] or "")
    return out


# ---------------------------------------------------------------------------
# HTTP wiring (bearer middleware + /health)
# ---------------------------------------------------------------------------

class StaticBearer(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("authorization", "") != f"Bearer {_BEARER}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(_request):
    return PlainTextResponse("ok")


app = mcp.http_app(transport="streamable-http")
app.add_middleware(StaticBearer)
app.routes.insert(0, Route("/health", health))
