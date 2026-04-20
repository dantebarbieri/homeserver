"""MCP wrapper around the local Valhalla routing engine."""
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

VALHALLA_URL = os.environ["VALHALLA_URL"].rstrip("/")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

mcp = FastMCP("valhalla")


@mcp.tool
async def route(
    locations: list[dict[str, float]],
    costing: str = "auto",
    units: str = "kilometers",
) -> dict[str, Any]:
    """Compute a route through ordered waypoints.

    Args:
        locations: List of {lat, lon} dicts, in order.
        costing: 'auto' | 'bicycle' | 'pedestrian' | 'bus' | 'truck' | 'multimodal'.
        units: 'kilometers' | 'miles'.
    """
    payload = {"locations": locations, "costing": costing, "units": units}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{VALHALLA_URL}/route", json=payload)
        r.raise_for_status()
    return r.json()


@mcp.tool
async def isochrone(
    lat: float,
    lon: float,
    contours_minutes: list[int],
    costing: str = "auto",
) -> dict[str, Any]:
    """Compute reachability isochrones from a single point.

    Args:
        lat: Origin latitude.
        lon: Origin longitude.
        contours_minutes: List of time contours in minutes (e.g. [10, 20, 30]).
        costing: Travel mode.
    """
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": costing,
        "contours": [{"time": m} for m in contours_minutes],
        "polygons": True,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{VALHALLA_URL}/isochrone", json=payload)
        r.raise_for_status()
    return r.json()


@mcp.tool
async def matrix(
    sources: list[dict[str, float]],
    targets: list[dict[str, float]],
    costing: str = "auto",
) -> dict[str, Any]:
    """Compute a sources-to-targets time/distance matrix.

    Args:
        sources: List of {lat, lon} origins.
        targets: List of {lat, lon} destinations.
        costing: Travel mode.
    """
    payload = {"sources": sources, "targets": targets, "costing": costing}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{VALHALLA_URL}/sources_to_targets", json=payload)
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
