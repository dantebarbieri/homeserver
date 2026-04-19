"""MCP wrapper around the local Photon instance.

Photon is the fuzzy/prefix/multilingual geocoder; complements Nominatim
(strict/structured). Use this when geocoding LLM-generated place strings
or when partial matches are useful.
"""
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

PHOTON_URL = os.environ["PHOTON_URL"].rstrip("/")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

mcp = FastMCP("photon")


@mcp.tool
async def search(
    q: str,
    limit: int = 10,
    lang: str = "en",
    lat: float | None = None,
    lon: float | None = None,
    osm_tag: str | None = None,
) -> dict[str, Any]:
    """Fuzzy-geocode a query via Photon. Returns GeoJSON FeatureCollection.

    Args:
        q: Free-text query (typo-tolerant).
        limit: Max results.
        lang: Result language ('en', 'de', 'fr', ...).
        lat: Optional bias latitude.
        lon: Optional bias longitude.
        osm_tag: Optional filter (e.g. 'place:city', 'amenity:restaurant').
    """
    params: dict[str, Any] = {"q": q, "limit": limit, "lang": lang}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    if osm_tag:
        params["osm_tag"] = osm_tag
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{PHOTON_URL}/api", params=params)
        r.raise_for_status()
    return r.json()


@mcp.tool
async def reverse(lat: float, lon: float, lang: str = "en", limit: int = 1) -> dict[str, Any]:
    """Reverse-geocode a lat/lon via Photon."""
    params = {"lat": lat, "lon": lon, "lang": lang, "limit": limit}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{PHOTON_URL}/reverse", params=params)
        r.raise_for_status()
    return r.json()


class StaticBearer(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("authorization", "") != f"Bearer {_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(_request):
    return PlainTextResponse("ok")


app = mcp.http_app(transport="streamable-http")
app.add_middleware(StaticBearer)
app.routes.insert(0, Route("/health", health))
