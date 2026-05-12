"""POST /token — authorization_code + refresh_token grants.

Issues:
    - access_token: RS256-signed JWT, 1h default TTL, ``aud = resource``.
    - id_token: RS256-signed JWT (only when scope includes "openid").
    - refresh_token: opaque random, hashed in storage. Rotated on every use.

Refresh-token rotation policy: strict. Replaying an already-used (revoked)
refresh token revokes the entire token family for (client_id, sub) per
RFC 9700 §4.14.2 BCP. We DO NOT implement a replay-grace window — easy
to add later via ``replaced_by_hash`` + a few-second window.
"""
from __future__ import annotations

import base64
import hashlib

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import AppConfig
from ..keys import JwtSigner
from ..security import (
    constant_time_eq,
    hash_secret,
    random_token,
    verify_hashed_secret,
)
from ..storage import Client, RefreshToken, Storage, now


def make_token_handler(config: AppConfig, storage: Storage, signer: JwtSigner):
    async def handler(request: Request) -> JSONResponse:
        form = await request.form()
        grant_type = (form.get("grant_type") or "").strip()
        if grant_type not in ("authorization_code", "refresh_token"):
            return _err(
                "unsupported_grant_type",
                f"grant_type {grant_type!r} not supported "
                f"(allowed: authorization_code, refresh_token)",
            )

        # Authenticate the client (Basic header OR form-post).
        auth = await _authenticate_client(request, form, storage, config)
        if isinstance(auth, JSONResponse):
            return auth
        client = auth

        if grant_type == "authorization_code":
            return await _grant_authorization_code(form, client, config, storage, signer)
        # grant_type == "refresh_token"
        return await _grant_refresh_token(form, client, config, storage, signer)

    return handler


# ---- client authentication ------------------------------------------------


async def _authenticate_client(
    request: Request, form, storage: Storage, config: AppConfig
):
    """Returns the authenticated Client, or a JSONResponse with the error."""
    cid_basic, secret_basic = _decode_basic(request.headers.get("authorization"))
    cid_form = (form.get("client_id") or "").strip() or None
    secret_form = (form.get("client_secret") or "").strip() or None

    if cid_basic is not None and cid_form is not None and cid_basic != cid_form:
        return _err(
            "invalid_request",
            "client_id mismatch between Authorization header and form body",
        )

    client_id = cid_basic or cid_form
    if not client_id:
        return _err("invalid_client", "missing client_id", status=401)

    client_secret = secret_basic or secret_form
    if not client_secret:
        return _err("invalid_client", "missing client_secret", status=401)

    client = await storage.get_client(client_id)
    if client is None or not verify_hashed_secret(
        client_secret, client.client_secret_hash, config.pepper
    ):
        return _err("invalid_client", "client authentication failed", status=401)

    return client


def _decode_basic(header: str | None) -> tuple[str | None, str | None]:
    if not header or not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    if ":" not in decoded:
        return None, None
    cid, _, secret = decoded.partition(":")
    return (cid or None), (secret or None)


# ---- authorization_code grant ---------------------------------------------


async def _grant_authorization_code(
    form, client: Client, config: AppConfig, storage: Storage, signer: JwtSigner
) -> JSONResponse:
    code = (form.get("code") or "").strip()
    redirect_uri = (form.get("redirect_uri") or "").strip()
    code_verifier = (form.get("code_verifier") or "").strip()
    resource = (form.get("resource") or "").strip() or None

    if not code or not redirect_uri or not code_verifier:
        return _err(
            "invalid_request",
            "code, redirect_uri, and code_verifier are required",
        )

    code_hash = hash_secret(code, config.pepper)
    auth_code = await storage.pop_auth_code(code_hash)
    if auth_code is None:
        return _err("invalid_grant", "code is invalid, expired, or already used")
    if auth_code.expires_at <= now():
        return _err("invalid_grant", "code has expired")
    if not constant_time_eq(auth_code.client_id, client.client_id):
        return _err("invalid_grant", "code was issued to a different client")
    if not constant_time_eq(auth_code.redirect_uri, redirect_uri):
        return _err("invalid_grant", "redirect_uri does not match the one in the auth request")

    # PKCE verification (S256).
    if not _verify_pkce_s256(code_verifier, auth_code.code_challenge):
        return _err("invalid_grant", "PKCE verification failed")

    # Resource consistency (if client sent it again at /token).
    if resource is not None and resource != auth_code.resource:
        return _err(
            "invalid_target",
            "resource at /token must match the resource sent at /authorize",
        )

    return await _issue_tokens(
        config=config,
        storage=storage,
        signer=signer,
        client=client,
        sub=auth_code.sub,
        scope=auth_code.scope,
        resource=auth_code.resource,
        nonce=auth_code.nonce,
    )


def _verify_pkce_s256(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return constant_time_eq(expected, challenge)


# ---- refresh_token grant --------------------------------------------------


async def _grant_refresh_token(
    form, client: Client, config: AppConfig, storage: Storage, signer: JwtSigner
) -> JSONResponse:
    raw = (form.get("refresh_token") or "").strip()
    if not raw:
        return _err("invalid_request", "refresh_token is required")
    requested_scope = (form.get("scope") or "").strip() or None
    requested_resource = (form.get("resource") or "").strip() or None

    token_hash = hash_secret(raw, config.pepper)
    rt = await storage.get_refresh_token(token_hash)
    if rt is None:
        return _err("invalid_grant", "refresh_token not found")
    if not constant_time_eq(rt.client_id, client.client_id):
        return _err("invalid_grant", "refresh_token was issued to a different client")
    if rt.expires_at <= now():
        return _err("invalid_grant", "refresh_token has expired")

    if rt.revoked_at is not None:
        # REPLAY DETECTED. Per RFC 9700 §4.14.2 BCP: revoke the entire family.
        await storage.revoke_refresh_token_family(client.client_id, rt.sub, now=now())
        return _err(
            "invalid_grant",
            "refresh_token replay detected; entire token family revoked",
        )

    # Resource: cannot upgrade to a different resource.
    if requested_resource is not None and requested_resource != rt.resource:
        return _err(
            "invalid_target",
            "resource on refresh must match the original resource",
        )

    # Scope: only narrowing is allowed.
    granted_scope = rt.scope
    if requested_scope is not None:
        original = set((rt.scope or "").split())
        requested = set(requested_scope.split())
        if not requested.issubset(original):
            return _err(
                "invalid_scope",
                "requested scope is broader than originally granted",
            )
        granted_scope = " ".join(sorted(requested)) or None

    # Issue new tokens, mark old as revoked + replaced.
    response, new_refresh_value = await _issue_tokens_returning_secret(
        config=config,
        storage=storage,
        signer=signer,
        client=client,
        sub=rt.sub,
        scope=granted_scope,
        resource=rt.resource,
        nonce=None,
    )
    new_hash = hash_secret(new_refresh_value, config.pepper)
    await storage.revoke_refresh_token(token_hash, now=now(), replaced_by_hash=new_hash)
    return response


# ---- token issuance -------------------------------------------------------


async def _issue_tokens(
    *,
    config: AppConfig,
    storage: Storage,
    signer: JwtSigner,
    client: Client,
    sub: str,
    scope: str | None,
    resource: str,
    nonce: str | None,
) -> JSONResponse:
    response, _ = await _issue_tokens_returning_secret(
        config=config,
        storage=storage,
        signer=signer,
        client=client,
        sub=sub,
        scope=scope,
        resource=resource,
        nonce=nonce,
    )
    return response


async def _issue_tokens_returning_secret(
    *,
    config: AppConfig,
    storage: Storage,
    signer: JwtSigner,
    client: Client,
    sub: str,
    scope: str | None,
    resource: str,
    nonce: str | None,
) -> tuple[JSONResponse, str]:
    """Issue + persist tokens. Returns (JSONResponse, cleartext refresh_token).

    The cleartext is returned separately so the refresh-rotation caller
    can ``hash_secret`` it and set ``replaced_by_hash`` on the old refresh
    token without re-parsing the response body.
    """
    iat = now()
    access_exp = iat + config.access_token_ttl
    access_claims: dict = {
        "iss": config.issuer,
        "sub": sub,
        "aud": resource,
        "client_id": client.client_id,
        "iat": iat,
        "exp": access_exp,
        "jti": random_token(16),
        "token_type": "access_token",
    }
    if scope:
        access_claims["scope"] = scope
    access_token = signer.sign(access_claims)

    refresh_value = random_token(32)
    refresh_hash = hash_secret(refresh_value, config.pepper)
    await storage.insert_refresh_token(
        RefreshToken(
            token_hash=refresh_hash,
            client_id=client.client_id,
            sub=sub,
            scope=scope,
            resource=resource,
            issued_at=iat,
            expires_at=iat + config.refresh_token_ttl,
            revoked_at=None,
            replaced_by_hash=None,
        )
    )

    body: dict = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": config.access_token_ttl,
        "refresh_token": refresh_value,
    }
    if scope:
        body["scope"] = scope
    if scope and "openid" in scope.split():
        id_claims: dict = {
            "iss": config.issuer,
            "sub": sub,
            "aud": client.client_id,
            "iat": iat,
            "exp": access_exp,
        }
        if nonce:
            id_claims["nonce"] = nonce
        body["id_token"] = signer.sign(id_claims)

    return (
        JSONResponse(
            body,
            status_code=200,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        ),
        refresh_value,
    )


def _err(code: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": code, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


__all__ = ["make_token_handler"]
