"""Bearer-auth + reverse proxy in front of mcp-proxy.

mcp-proxy bridges a stdio MCP server to Streamable HTTP but does not
enforce bearer auth. This Starlette app validates the bearer header and
forwards all other traffic (including streamed responses) to mcp-proxy
on 127.0.0.1:8081.
"""
import os

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

UPSTREAM = os.getenv("MCP_PROXY_UPSTREAM", "http://127.0.0.1:8081")
with open(os.environ["AUTH_TOKEN_FILE"]) as _f:
    _TOKEN = _f.read().strip()

# Module-scoped client for connection reuse and so a failure in send()
# can't leak a per-request client.
_CLIENT = httpx.AsyncClient(timeout=None)


class StaticBearer(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("authorization", "") != f"Bearer {_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(_request):
    return PlainTextResponse("ok")


async def proxy(request):
    url = f"{UPSTREAM}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    body = await request.body()
    upstream_req = _CLIENT.build_request(request.method, url, headers=headers, content=body)
    upstream = await _CLIENT.send(upstream_req, stream=True)

    async def aiter():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    out_headers = {k: v for k, v in upstream.headers.items()
                   if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")}
    return StreamingResponse(aiter(), status_code=upstream.status_code, headers=out_headers)


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/{path:path}", proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
    ],
    middleware=[Middleware(StaticBearer)],
)
