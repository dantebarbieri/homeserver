"""POST /revoke — RFC 7009 token revocation.

Revokes refresh tokens by hash. Access tokens are JWTs and not stored
server-side (we don't have an introspection/revocation list for JWTs);
revocation requests for access-token-typed tokens are silently accepted
per RFC 7009 §2.2 ("the authorization server SHOULD NOT consider a
revocation request for a token that is not its own as an error").
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import AppConfig
from ..security import hash_secret, verify_hashed_secret
from ..storage import Storage, now


def make_revoke_handler(config: AppConfig, storage: Storage):
    async def handler(request: Request) -> Response:
        form = await request.form()
        token = (form.get("token") or "").strip()
        if not token:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "token is required"},
                status_code=400,
            )

        # Authenticate the client (Basic header OR form-post).
        # Reuse the token endpoint's logic via a minimal inline copy to
        # avoid coupling the modules.
        from .token import _authenticate_client  # local import — endpoint helper

        auth = await _authenticate_client(request, form, storage, config)
        if isinstance(auth, JSONResponse):
            return auth
        client = auth

        # Try refresh-token revocation. Access tokens are JWTs (stateless);
        # we don't track them server-side.
        token_hash = hash_secret(token, config.pepper)
        rt = await storage.get_refresh_token(token_hash)
        if rt is not None:
            if rt.client_id != client.client_id:
                # Don't leak whether the token exists — silently succeed
                # per RFC 7009 §2.1.
                return Response(status_code=200)
            await storage.revoke_refresh_token(token_hash, now=now())

        # RFC 7009 §2.2 — always 200 even if token wasn't found.
        # `verify_hashed_secret` is unused here but imported for future
        # introspection-endpoint reuse; keep the import consistent.
        _ = verify_hashed_secret
        return Response(status_code=200)

    return handler


__all__ = ["make_revoke_handler"]
