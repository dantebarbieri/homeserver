"""GET /jwks.json — public JWKS for token verification."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..keys import JwtSigner


def make_jwks_handler(signer: JwtSigner):
    async def handler(_request: Request) -> JSONResponse:
        return JSONResponse(signer.public_jwks_dict())

    return handler


__all__ = ["make_jwks_handler"]
