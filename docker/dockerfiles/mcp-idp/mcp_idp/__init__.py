"""mcp-idp — tiny single-user OIDC IdP with Dynamic Client Registration.

The ``app`` symbol is what ``uvicorn mcp_idp:app`` (the production entry
point in the Dockerfile) imports. Lazy via PEP 562 :func:`__getattr__` so
that importing sibling modules in tests doesn't trigger ``AppConfig.from_env``.

The factory + route wiring live in :mod:`mcp_idp.server` (not
``mcp_idp.app``) — naming the submodule ``app`` would shadow the lazy
attribute defined here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .server import create_app

if TYPE_CHECKING:
    from starlette.applications import Starlette

__all__ = ["create_app", "app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        global app  # noqa: PLW0603 — module-level singleton cache
        app = create_app()
        return app
    raise AttributeError(f"module 'mcp_idp' has no attribute {name!r}")


if TYPE_CHECKING:
    app: Starlette
