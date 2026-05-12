"""POST /register — RFC 7591 Dynamic Client Registration.

Accepts a JSON body matching the RFC 7591 client_metadata shape, returns
the client_information_response with the freshly-minted ``client_id`` and
(plaintext, exactly once) ``client_secret``.

Open registration: no initial access token required. Acceptable for the
"single-user homeserver" threat model because the consent screen at
``/authorize`` requires the operator's auth-proxy login (typically
2FA-protected Authelia) — registering a client without being able to
complete consent yields a useless client. Hardening still applied:

- Body size capped (cheap content-length check).
- Field-length caps (``client_name``).
- Redirect URI count capped + each URI validated (https-only by default,
  no fragments).
- Grant types restricted to {authorization_code, refresh_token}.
- Client secret stored as HMAC-SHA256 hash (no bcrypt — generated secrets
  are 256 bits of entropy; bcrypt would just be a DoS amplifier).
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import AppConfig
from ..security import hash_secret, random_id, random_token
from ..storage import Client, Storage, now

_DEFAULT_GRANT_TYPES = ("authorization_code", "refresh_token")
_DEFAULT_RESPONSE_TYPES = ("code",)
_ALLOWED_GRANT_TYPES = {"authorization_code", "refresh_token"}
_ALLOWED_RESPONSE_TYPES = {"code"}
_ALLOWED_AUTH_METHODS = {"client_secret_basic", "client_secret_post"}


def make_register_handler(config: AppConfig, storage: Storage):
    async def handler(request: Request) -> JSONResponse:
        cl = request.headers.get("content-length")
        if cl and int(cl) > config.dcr_max_body_bytes:
            return _err("invalid_client_metadata", "request body too large", 413)

        try:
            raw = await request.body()
            if len(raw) > config.dcr_max_body_bytes:
                return _err("invalid_client_metadata", "request body too large", 413)
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return _err("invalid_client_metadata", "request body must be JSON", 400)
        if not isinstance(body, dict):
            return _err("invalid_client_metadata", "request body must be a JSON object", 400)

        # ---- redirect_uris (REQUIRED for authorization_code) -------------
        ru = body.get("redirect_uris")
        if not isinstance(ru, list) or not ru:
            return _err(
                "invalid_redirect_uri",
                "redirect_uris is required and must be a non-empty list",
            )
        if len(ru) > config.dcr_max_redirect_uris:
            return _err(
                "invalid_redirect_uri",
                f"redirect_uris exceeds max ({config.dcr_max_redirect_uris})",
            )
        validated_uris: list[str] = []
        for uri in ru:
            if not isinstance(uri, str):
                return _err("invalid_redirect_uri", "all redirect_uris must be strings")
            err = _validate_redirect_uri(uri, config.dcr_allow_http_redirects)
            if err:
                return _err("invalid_redirect_uri", err)
            validated_uris.append(uri)

        # ---- grant_types --------------------------------------------------
        gt = body.get("grant_types") or list(_DEFAULT_GRANT_TYPES)
        if not isinstance(gt, list):
            return _err("invalid_client_metadata", "grant_types must be a list")
        for g in gt:
            if g not in _ALLOWED_GRANT_TYPES:
                return _err(
                    "invalid_client_metadata",
                    f"grant_type {g!r} not supported "
                    f"(allowed: {sorted(_ALLOWED_GRANT_TYPES)})",
                )
        # If `authorization_code` is requested, redirect_uris already validated above.

        # ---- response_types ----------------------------------------------
        rt = body.get("response_types") or list(_DEFAULT_RESPONSE_TYPES)
        if not isinstance(rt, list):
            return _err("invalid_client_metadata", "response_types must be a list")
        for r in rt:
            if r not in _ALLOWED_RESPONSE_TYPES:
                return _err(
                    "invalid_client_metadata",
                    f"response_type {r!r} not supported (allowed: ['code'])",
                )

        # ---- token_endpoint_auth_method ----------------------------------
        team = body.get("token_endpoint_auth_method", "client_secret_basic")
        if team not in _ALLOWED_AUTH_METHODS:
            return _err(
                "invalid_client_metadata",
                f"token_endpoint_auth_method {team!r} not supported "
                f"(allowed: {sorted(_ALLOWED_AUTH_METHODS)})",
            )

        # ---- client_name -------------------------------------------------
        name = body.get("client_name")
        if name is not None:
            if not isinstance(name, str):
                return _err("invalid_client_metadata", "client_name must be a string")
            if len(name) > config.dcr_max_name_len:
                return _err(
                    "invalid_client_metadata",
                    f"client_name exceeds max length ({config.dcr_max_name_len})",
                )

        # ---- scope --------------------------------------------------------
        scope = body.get("scope")
        if scope is not None and not isinstance(scope, str):
            return _err("invalid_client_metadata", "scope must be a space-separated string")

        # ---- generate credentials + persist ------------------------------
        client_id = random_id(prefix="dcr-", nbytes=16)  # ~22-char tail
        client_secret = random_token(32)  # 256-bit entropy
        client_secret_hash = hash_secret(client_secret, config.pepper)

        await storage.insert_client(
            Client(
                client_id=client_id,
                client_secret_hash=client_secret_hash,
                client_name=name,
                redirect_uris=tuple(validated_uris),
                grant_types=tuple(gt),
                response_types=tuple(rt),
                token_endpoint_auth_method=team,
                scope=scope,
                registered_at=now(),
            )
        )

        # RFC 7591 client_information_response. We do NOT return
        # `registration_access_token` / `registration_client_uri` because
        # we don't implement RFC 7592 (client management endpoint).
        return JSONResponse(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "client_secret_expires_at": 0,  # never expires
                "client_id_issued_at": now(),
                "redirect_uris": validated_uris,
                "grant_types": gt,
                "response_types": rt,
                "token_endpoint_auth_method": team,
                **({"client_name": name} if name else {}),
                **({"scope": scope} if scope else {}),
            },
            status_code=201,
        )

    return handler


def _validate_redirect_uri(uri: str, allow_http: bool) -> str | None:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return f"redirect_uri {uri!r} is not a valid URL"
    if parsed.scheme not in ("https", "http"):
        return f"redirect_uri {uri!r} must be http(s)"
    if parsed.scheme == "http" and not allow_http:
        return f"redirect_uri {uri!r} must be https (set IDP_DCR_ALLOW_HTTP_REDIRECTS=true to override for dev)"
    if parsed.fragment:
        return f"redirect_uri {uri!r} must not contain a fragment"
    if not parsed.netloc:
        return f"redirect_uri {uri!r} missing host"
    return None


def _err(code: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": code, "error_description": description}, status_code=status
    )


__all__ = ["make_register_handler"]
