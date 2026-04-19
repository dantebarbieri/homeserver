"""MCP wrapper around the local Nominatim instance.

Exposes search (forward geocode), reverse, and lookup tools. Bearer-auth
enforced via Starlette middleware reading AUTH_TOKEN_FILE.
"""
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

NOMINATIM_URL = os.environ["NOMINATIM_URL"].rstrip("/")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

mcp = FastMCP("nominatim")


@mcp.tool
async def search(
    q: str,
    limit: int = 10,
    countrycodes: str | None = None,
    addressdetails: bool = True,
) -> list[dict[str, Any]]:
    """Forward-geocode a free-text query. Returns ranked candidate places.

    Args:
        q: Free-text query (place name, address, landmark).
        limit: Max results.
        countrycodes: Comma-separated ISO 3166-1 alpha-2 codes to restrict to.
        addressdetails: Include parsed address components.
    """
    params: dict[str, Any] = {"q": q, "format": "jsonv2", "limit": limit,
                              "addressdetails": int(addressdetails)}
    if countrycodes:
        params["countrycodes"] = countrycodes
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{NOMINATIM_URL}/search", params=params)
        r.raise_for_status()
    return r.json()


@mcp.tool
async def reverse(lat: float, lon: float, zoom: int = 18) -> dict[str, Any]:
    """Reverse-geocode a lat/lon to a structured address.

    Args:
        lat: Latitude in WGS-84.
        lon: Longitude in WGS-84.
        zoom: Detail level (3=country, 18=building).
    """
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": zoom,
              "addressdetails": 1}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{NOMINATIM_URL}/reverse", params=params)
        r.raise_for_status()
    return r.json()


@mcp.tool
async def lookup(osm_ids: str) -> list[dict[str, Any]]:
    """Look up places by OSM IDs (e.g. 'N123,W456,R789')."""
    params = {"osm_ids": osm_ids, "format": "jsonv2", "addressdetails": 1}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{NOMINATIM_URL}/lookup", params=params)
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
