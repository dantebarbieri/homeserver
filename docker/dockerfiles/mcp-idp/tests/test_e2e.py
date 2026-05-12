"""End-to-end test: DCR → /authorize → consent approve → /token → /token refresh.

Exercises the full happy-path flow plus the security-critical refresh-token
replay-revokes-family path.
"""
from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

from joserfc import jwt
from joserfc.jwk import KeySet
from starlette.testclient import TestClient

# Mirror of the constants in conftest.py — duplicated here because pytest
# test files aren't a package and relative imports don't work.
PROXY_HEADER = "X-Test-User"
RESOURCE = "https://mcp-tcad.test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) where challenge = b64url(SHA256(verifier))."""
    verifier = base64.urlsafe_b64encode(b"_" * 64).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _register(client: TestClient, redirect_uri: str = "https://claude.ai/cb") -> dict:
    r = client.post(
        "/register",
        json={
            "client_name": "Test Client",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "openid profile",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _extract_form_fields(html: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'<input type="hidden" name="(\w+)" value="([^"]+)"', html
        )
    }


def _start_auth(
    client: TestClient,
    *,
    client_id: str,
    redirect_uri: str = "https://claude.ai/cb",
    scope: str = "openid profile",
    challenge: str,
    state: str = "abc123",
    user: str = "alice",
) -> dict[str, str]:
    """Run GET /authorize, return the hidden form fields from the consent screen."""
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        headers={PROXY_HEADER: user},
    )
    assert r.status_code == 200, r.text
    fields = _extract_form_fields(r.text)
    assert "auth_request_id" in fields and "csrf_token" in fields
    return fields


def _approve(client: TestClient, fields: dict[str, str], user: str = "alice"):
    return client.post(
        "/authorize",
        data={
            "auth_request_id": fields["auth_request_id"],
            "csrf_token": fields["csrf_token"],
            "decision": "approve",
        },
        headers={PROXY_HEADER: user},
        follow_redirects=False,
    )


def _exchange_code(
    client: TestClient,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    verifier: str,
):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_flow(client: TestClient) -> None:
    # Discovery is reachable + lists registration_endpoint
    disc = client.get("/.well-known/openid-configuration").json()
    assert disc["registration_endpoint"].endswith("/register")
    assert disc["code_challenge_methods_supported"] == ["S256"]
    assert disc["resource_indicators_supported"] is True

    # Register a client via DCR
    creds = _register(client)
    assert creds["client_id"].startswith("dcr-")
    assert len(creds["client_secret"]) >= 32

    # Run the full authorization_code flow
    verifier, challenge = _pkce_pair()
    fields = _start_auth(
        client, client_id=creds["client_id"], challenge=challenge
    )
    redirect = _approve(client, fields)
    assert redirect.status_code == 303
    parsed = urlparse(redirect.headers["location"])
    qs = parse_qs(parsed.query)
    assert qs["state"] == ["abc123"]
    assert qs["iss"][0].startswith("https://")
    code = qs["code"][0]

    # Exchange code for tokens
    tok = _exchange_code(
        client,
        code=code,
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        redirect_uri="https://claude.ai/cb",
        verifier=verifier,
    )
    assert tok.status_code == 200, tok.text
    body = tok.json()
    assert body["token_type"] == "Bearer"
    assert "access_token" in body and "refresh_token" in body
    assert "id_token" in body  # because scope=openid

    # Validate the access token's JWT signature against /jwks.json
    jwks = client.get("/jwks.json").json()
    keyset = KeySet.import_key_set(jwks)
    decoded = jwt.decode(body["access_token"], keyset, algorithms=["RS256"])
    claims = decoded.claims
    assert claims["iss"].startswith("https://")
    assert claims["aud"] == RESOURCE
    assert claims["client_id"] == creds["client_id"]
    assert claims["sub"].startswith("sub:")
    assert claims["scope"] == "openid profile"

    # Refresh — should rotate to new tokens
    refresh1 = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert refresh1.status_code == 200, refresh1.text
    body2 = refresh1.json()
    assert body2["access_token"] != body["access_token"]
    assert body2["refresh_token"] != body["refresh_token"]

    # Replay the ORIGINAL (now-revoked) refresh token — should fail AND
    # revoke the family (the new refresh token is also invalidated).
    replay = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    # The new refresh token should now also be revoked (family wipe).
    after_replay = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": body2["refresh_token"],
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
        },
    )
    assert after_replay.status_code == 400


def test_authorize_requires_proxy_header(client: TestClient) -> None:
    creds = _register(client)
    _, challenge = _pkce_pair()
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": creds["client_id"],
            "redirect_uri": "https://claude.ai/cb",
            "state": "x",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        # no proxy header
    )
    assert r.status_code == 401


def test_authorize_rejects_unknown_resource(client: TestClient) -> None:
    creds = _register(client)
    _, challenge = _pkce_pair()
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": creds["client_id"],
            "redirect_uri": "https://claude.ai/cb",
            "state": "x",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": "https://not-allowlisted.test",
        },
        headers={PROXY_HEADER: "alice"},
    )
    assert r.status_code == 400


def test_authorize_requires_pkce_s256(client: TestClient) -> None:
    creds = _register(client)
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": creds["client_id"],
            "redirect_uri": "https://claude.ai/cb",
            "state": "x",
            "resource": RESOURCE,
            # no code_challenge / code_challenge_method
        },
        headers={PROXY_HEADER: "alice"},
    )
    assert r.status_code == 400


def test_token_invalid_pkce_rejected(client: TestClient) -> None:
    creds = _register(client)
    verifier, challenge = _pkce_pair()
    fields = _start_auth(
        client, client_id=creds["client_id"], challenge=challenge
    )
    redirect = _approve(client, fields)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
    # Use the WRONG verifier
    bad = _exchange_code(
        client,
        code=code,
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        redirect_uri="https://claude.ai/cb",
        verifier=verifier + "tampered",
    )
    assert bad.status_code == 400
    assert bad.json()["error"] == "invalid_grant"


def test_token_resource_mismatch_rejected(client: TestClient) -> None:
    creds = _register(client)
    verifier, challenge = _pkce_pair()
    fields = _start_auth(
        client, client_id=creds["client_id"], challenge=challenge
    )
    redirect = _approve(client, fields)
    code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
    # /token with a *different* resource than was bound at /authorize
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/cb",
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "resource": "https://other.test",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_target"


def test_register_rejects_http_redirect_when_disallowed(
    client: TestClient, config
) -> None:
    # Override the conftest fixture to disable http redirects.
    from mcp_idp.config import AppConfig
    from mcp_idp.server import create_app

    cfg = AppConfig(**{**config.__dict__, "dcr_allow_http_redirects": False})
    app = create_app(cfg)
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"redirect_uris": ["http://localhost/cb"]},
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_redirect_uri"


def test_consent_csrf_check(client: TestClient) -> None:
    creds = _register(client)
    _, challenge = _pkce_pair()
    fields = _start_auth(
        client, client_id=creds["client_id"], challenge=challenge
    )
    # Use a wrong CSRF token — POST should be rejected.
    r = client.post(
        "/authorize",
        data={
            "auth_request_id": fields["auth_request_id"],
            "csrf_token": "wrong",
            "decision": "approve",
        },
        headers={PROXY_HEADER: "alice"},
        follow_redirects=False,
    )
    assert r.status_code == 403
