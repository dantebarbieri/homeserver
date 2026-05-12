"""GET /.well-known/openid-configuration — OIDC discovery doc.

Only advertises features actually implemented. We're an MCP-purpose IdP, so
we deliberately omit ``userinfo_endpoint`` (we put everything in the JWT)
and any flow we don't implement (implicit, password, client_credentials,
device_code, hybrid).
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


def make_discovery_handler(issuer: str):
    body = _build_discovery_doc(issuer)

    async def handler(_request: Request) -> JSONResponse:
        return JSONResponse(body)

    return handler


def _build_discovery_doc(issuer: str) -> dict:
    issuer = issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "revocation_endpoint": f"{issuer}/revoke",
        "jwks_uri": f"{issuer}/jwks.json",
        # No userinfo_endpoint — we mint everything into the JWT.
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["openid", "profile"],
        # RFC 8707 — we require `resource` on /authorize.
        "resource_indicators_supported": True,
        # Per the MCP authorization spec, advertise that we accept
        # the `resource` parameter at both endpoints.
        "authorization_response_iss_parameter_supported": True,
    }


__all__ = ["make_discovery_handler"]
