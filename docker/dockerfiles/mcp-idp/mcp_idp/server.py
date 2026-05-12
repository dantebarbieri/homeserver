"""create_app — Starlette app factory + route wiring + lifespan management.

Reads :class:`AppConfig` from env, opens SQLite, loads or generates the
JWKS keypair, wires routes, returns a Starlette ASGI app.

Lifespan: opens the storage connection at startup, closes it at shutdown.
A periodic GC sweep is NOT implemented (storage tables stay small for
single-user homeserver use); add a startup task later if needed.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from .config import AppConfig
from .endpoints.authorize import make_authorize_handlers
from .endpoints.discovery import make_discovery_handler
from .endpoints.health import healthz
from .endpoints.jwks import make_jwks_handler
from .endpoints.register import make_register_handler
from .endpoints.revoke import make_revoke_handler
from .endpoints.token import make_token_handler
from .keys import load_or_create_signer
from .storage import Storage


def create_app(config: AppConfig | None = None) -> Starlette:
    cfg = config or AppConfig.from_env()
    signer = load_or_create_signer(cfg.keys_path)
    storage = Storage(cfg.db_path)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await storage.init()
        try:
            yield
        finally:
            await storage.close()

    discovery = make_discovery_handler(cfg.issuer)
    jwks = make_jwks_handler(signer)
    register = make_register_handler(cfg, storage)
    authorize_get, authorize_post = make_authorize_handlers(cfg, storage)
    token = make_token_handler(cfg, storage, signer)
    revoke = make_revoke_handler(cfg, storage)

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route(
            "/.well-known/openid-configuration",
            discovery,
            methods=["GET"],
        ),
        # MCP authorization spec also looks for /.well-known/oauth-authorization-server
        # at the issuer — RFC 8414. Same response shape, alias for compat.
        Route(
            "/.well-known/oauth-authorization-server",
            discovery,
            methods=["GET"],
        ),
        Route("/jwks.json", jwks, methods=["GET"]),
        Route("/register", register, methods=["POST"]),
        Route("/authorize", authorize_get, methods=["GET"]),
        Route("/authorize", authorize_post, methods=["POST"]),
        Route("/token", token, methods=["POST"]),
        Route("/revoke", revoke, methods=["POST"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        ),
    ]

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


__all__ = ["create_app"]
