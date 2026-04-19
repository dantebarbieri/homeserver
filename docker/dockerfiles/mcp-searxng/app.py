"""MCP wrapper around the AI-private SearXNG (ai-search.danteb.com).

Exposes a single `search` tool that hits SearXNG's JSON API. Bearer-auth
enforced via Starlette middleware reading AUTH_TOKEN_FILE.
"""
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

SEARXNG_URL = os.environ["SEARXNG_URL"].rstrip("/")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

mcp = FastMCP("searxng")


@mcp.tool
async def search(
    query: str,
    categories: str = "general",
    language: str = "en",
    pageno: int = 1,
    time_range: str | None = None,
) -> dict[str, Any]:
    """Search the AI-private SearXNG instance.

    Args:
        query: Free-text search query.
        categories: Comma-separated category list (general, news, science, etc.).
        language: ISO 639-1 language code or 'all'.
        pageno: 1-indexed page number.
        time_range: Optional 'day' | 'week' | 'month' | 'year'.
    """
    params = {"q": query, "format": "json", "categories": categories,
              "language": language, "pageno": pageno}
    if time_range:
        params["time_range"] = time_range
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SEARXNG_URL}/search", params=params)
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
