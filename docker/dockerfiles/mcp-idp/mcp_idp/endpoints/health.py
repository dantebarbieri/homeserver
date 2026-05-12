"""GET /healthz — container healthcheck endpoint."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import PlainTextResponse


async def healthz(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")
