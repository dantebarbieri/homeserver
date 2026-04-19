"""MCP wrapper around the local opentopodata server (Copernicus GLO-30)."""
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

OPENTOPODATA_URL = os.environ["OPENTOPODATA_URL"].rstrip("/")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

mcp = FastMCP("elevation")


def _format_locations(locations: list[dict[str, float]]) -> str:
    return "|".join(f"{p['lat']},{p['lon']}" for p in locations)


@mcp.tool
async def lookup(
    locations: list[dict[str, float]],
    dataset: str = "cop30",
    interpolation: str = "bilinear",
) -> dict[str, Any]:
    """Look up elevation for one or more lat/lon points.

    Args:
        locations: List of {lat, lon} points (max 100 per request).
        dataset: 'cop30' (Copernicus GLO-30, primary) or 'srtm30m' (void fallback).
        interpolation: 'nearest' | 'bilinear' | 'cubic'.
    """
    params = {
        "locations": _format_locations(locations),
        "interpolation": interpolation,
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{OPENTOPODATA_URL}/v1/{dataset}", params=params)
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
