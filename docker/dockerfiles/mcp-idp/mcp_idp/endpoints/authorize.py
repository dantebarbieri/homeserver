"""GET + POST /authorize — authorization endpoint with server-side
transaction binding for consent CSRF protection.

Flow:
    GET /authorize?client_id=...&redirect_uri=...&...
        1. Verify proxy secret + read authenticated user from proxy header
        2. Validate request params
        3. Look up client + validate redirect_uri / scope / resource
        4. Map proxy_user -> stable opaque sub
        5. Generate auth_request_id + csrf_token, store request transaction
        6. Render consent.html

    POST /authorize  (form: auth_request_id, csrf_token, decision)
        1. Verify proxy secret + same authenticated user
        2. Pop the auth_request transaction (single-use)
        3. Verify CSRF token matches what we issued
        4. Verify the SAME proxy user that initiated the request is consenting
        5. If approve: generate auth code, store hash, redirect to client
        6. If deny: redirect to client with error=access_denied

The POST submits ONLY (auth_request_id, csrf_token, decision). All
security-critical params (client_id, redirect_uri, scope, resource,
code_challenge, etc.) are pulled from the stored transaction, never from
the form. This blocks the request-swap attack the rubber-duck flagged.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.templating import Jinja2Templates

from ..config import AppConfig
from ..security import hash_secret, random_token, verify_hashed_secret
from ..storage import AuthCode, AuthRequest, Storage, now

_TEMPLATES_DIR = str(Path(__file__).resolve().parent.parent / "templates")


def _make_templates() -> Jinja2Templates:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "htm"]),
    )
    return Jinja2Templates(env=env)


_templates: Jinja2Templates | None = None


def _get_templates() -> Jinja2Templates:
    global _templates  # noqa: PLW0603 — singleton cache
    if _templates is None:
        _templates = _make_templates()
    return _templates


def make_authorize_handlers(config: AppConfig, storage: Storage):
    """Returns (GET handler, POST handler)."""

    async def get_authorize(request: Request) -> Response:
        proxy_check = _check_proxy(request, config)
        if proxy_check is not None:
            return proxy_check

        proxy_user = (request.headers.get(config.proxy_header_user) or "").strip()
        if not proxy_user:
            # NPM ForwardAuth should never let this through unauthenticated;
            # this is defense-in-depth in case someone reaches us directly.
            return _html_error(
                "Authentication required",
                "This endpoint requires authentication via the homeserver's "
                "auth proxy. If you reached this page directly, that's a "
                "deployment misconfiguration.",
                401,
            )

        params = request.query_params
        # Required params per OAuth 2.0 + MCP authorization spec:
        client_id = params.get("client_id", "").strip()
        redirect_uri = params.get("redirect_uri", "").strip()
        response_type = params.get("response_type", "").strip()
        state = params.get("state", "").strip()
        code_challenge = params.get("code_challenge", "").strip()
        code_challenge_method = params.get("code_challenge_method", "").strip()
        resource = params.get("resource", "").strip()
        # Optional:
        scope = (params.get("scope") or "").strip() or None
        nonce = (params.get("nonce") or "").strip() or None

        if response_type != "code":
            return _html_error(
                "Invalid request",
                f"response_type must be 'code' (got {response_type!r})",
                400,
            )
        if not state:
            return _html_error(
                "Invalid request", "state parameter is required", 400
            )
        if not code_challenge or code_challenge_method != "S256":
            return _html_error(
                "Invalid request",
                "PKCE is required: send code_challenge and code_challenge_method=S256",
                400,
            )
        if not resource:
            return _html_error(
                "Invalid request",
                "resource parameter is required (RFC 8707) — specify the URL "
                "of the MCP server you want a token for",
                400,
            )
        if resource not in config.resource_allowlist:
            return _html_error(
                "Invalid resource",
                f"resource {resource!r} is not in the configured allowlist. "
                f"Allowed: {list(config.resource_allowlist)}",
                400,
            )
        if not client_id:
            return _html_error("Invalid request", "client_id is required", 400)

        client = await storage.get_client(client_id)
        if client is None:
            return _html_error("Unknown client", f"client_id {client_id!r} not found", 400)

        if redirect_uri not in client.redirect_uris:
            return _html_error(
                "Invalid redirect_uri",
                "redirect_uri does not exactly match a registered URI for this client",
                400,
            )

        if "authorization_code" not in client.grant_types:
            return _html_error(
                "Unauthorized client",
                "this client is not registered for the authorization_code grant",
                400,
            )

        # Map proxy user -> stable opaque sub. Survives username renames.
        sub = await storage.get_or_create_subject(proxy_user, now=now())

        # Generate transaction
        auth_request_id = random_token(24)
        csrf_token = random_token(24)
        ar = AuthRequest(
            auth_request_id=auth_request_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
            resource=resource,
            sub=sub,
            csrf_token_hash=hash_secret(csrf_token, config.pepper),
            expires_at=now() + config.auth_request_ttl,
        )
        await storage.insert_auth_request(ar)

        templates = _get_templates()
        display_name = (
            request.headers.get(config.proxy_header_name) or proxy_user
        ).strip()
        return templates.TemplateResponse(
            request,
            "consent.html",
            {
                "client_name": client.client_name or client_id,
                "client_id": client_id,
                "scope": scope or "(none)",
                "resource": resource,
                "user_display": display_name,
                "auth_request_id": auth_request_id,
                "csrf_token": csrf_token,
            },
        )

    async def post_authorize(request: Request) -> Response:
        proxy_check = _check_proxy(request, config)
        if proxy_check is not None:
            return proxy_check

        proxy_user = (request.headers.get(config.proxy_header_user) or "").strip()
        if not proxy_user:
            return _html_error(
                "Authentication required", "missing proxy auth headers", 401
            )

        form = await request.form()
        auth_request_id = (form.get("auth_request_id") or "").strip()
        csrf_token = (form.get("csrf_token") or "").strip()
        decision = (form.get("decision") or "").strip()

        if not auth_request_id or not csrf_token or decision not in ("approve", "deny"):
            return _html_error(
                "Invalid request", "missing or malformed form fields", 400
            )

        ar = await storage.pop_auth_request(auth_request_id)
        if ar is None:
            return _html_error(
                "Expired or unknown request",
                "this authorization request has expired or already been used. "
                "Restart the consent flow from your client.",
                400,
            )
        if ar.expires_at <= now():
            return _html_error(
                "Expired request",
                "this authorization request has expired. Restart from your client.",
                400,
            )

        # CSRF check (constant-time).
        if not verify_hashed_secret(csrf_token, ar.csrf_token_hash, config.pepper):
            return _html_error(
                "CSRF check failed",
                "the consent form was tampered with or replayed",
                403,
            )

        # Bind the consenting user to the user that initiated the request —
        # blocks a session-swap-mid-flow attack.
        sub_at_consent = await storage.get_or_create_subject(proxy_user, now=now())
        if sub_at_consent != ar.sub:
            return _html_error(
                "User mismatch",
                "the user consenting is different from the user who initiated "
                "the authorization request",
                403,
            )

        if decision == "deny":
            return _redirect_with_params(
                ar.redirect_uri,
                {"error": "access_denied", "state": ar.state, "iss": config.issuer},
            )

        # Generate auth code, hash it, persist.
        code = random_token(32)
        await storage.insert_auth_code(
            AuthCode(
                code_hash=hash_secret(code, config.pepper),
                client_id=ar.client_id,
                redirect_uri=ar.redirect_uri,
                scope=ar.scope,
                code_challenge=ar.code_challenge,
                code_challenge_method=ar.code_challenge_method,
                nonce=ar.nonce,
                sub=ar.sub,
                resource=ar.resource,
                expires_at=now() + config.auth_code_ttl,
            )
        )
        return _redirect_with_params(
            ar.redirect_uri,
            {"code": code, "state": ar.state, "iss": config.issuer},
        )

    return get_authorize, post_authorize


# ---- helpers --------------------------------------------------------------


def _check_proxy(request: Request, config: AppConfig) -> Response | None:
    """If IDP_PROXY_SECRET is configured, require a matching value in the
    ``X-Internal-Auth-Proxy-Secret`` header. Returns a 403 response on
    mismatch, None on success or when no secret is configured."""
    if not config.proxy_secret:
        return None
    sent = request.headers.get("x-internal-auth-proxy-secret", "")
    # Constant-time compare to avoid leaking the secret length over timing.
    import hmac

    if not hmac.compare_digest(sent, config.proxy_secret):
        return _html_error(
            "Forbidden",
            "this endpoint is reachable only through the configured auth proxy",
            403,
        )
    return None


def _html_error(title: str, body: str, status: int) -> HTMLResponse:
    # Minimal inline HTML; no template needed.
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    safe_body = body.replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f"<!doctype html><html><head><title>{safe_title}</title>"
        f"<style>body{{font-family:system-ui;max-width:42em;margin:4em auto;padding:0 1em}}"
        f"h1{{color:#b00}}</style></head>"
        f"<body><h1>{safe_title}</h1><p>{safe_body}</p></body></html>",
        status_code=status,
    )


def _redirect_with_params(base: str, params: dict[str, str]) -> RedirectResponse:
    sep = "&" if "?" in base else "?"
    qs = urlencode(params)
    # 303 ensures POST-redirect-GET semantics so the user-agent issues a GET
    # to the client's redirect URI even though we're responding to a POST.
    return RedirectResponse(f"{base}{sep}{qs}", status_code=303)


__all__ = ["make_authorize_handlers"]
