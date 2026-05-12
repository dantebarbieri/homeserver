"""Environment-driven configuration for mcp-idp.

Import-time-safe — ``AppConfig.from_env`` is only called by ``create_app``
at startup, not at module import time. Tests can import sibling modules
without setting env vars.

All long-lived secrets follow the standard Docker `ENV_VAR` /
`ENV_VAR_FILE` convention (env wins over file when both set).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _strip_or_none(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return s or None


def _load_secret(env_var: str) -> str | None:
    """Load a secret from either ``ENV_VAR`` or ``ENV_VAR_FILE``."""
    direct = _strip_or_none(os.environ.get(env_var))
    if direct:
        return direct
    file_env = os.environ.get(f"{env_var}_FILE")
    if file_env:
        path = file_env.strip()
        if path:
            with open(path) as f:
                return f.read().strip() or None
    return None


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class AppConfig:
    issuer: str
    db_path: str
    keys_path: str
    pepper: str
    """Server-side secret used to HMAC-hash client_secrets, auth codes, and
    refresh tokens. Generate with ``openssl rand -hex 32``. Required."""

    resource_allowlist: tuple[str, ...]
    """Allowed RFC 8707 ``resource`` indicators. Required + non-empty so we
    never mint audience-less MCP tokens (RFC 9728 §7.4 confused-deputy)."""

    proxy_header_user: str
    """Request header to read the authenticated username from. Set by NPM
    after Authelia ForwardAuth (typical: ``X-Authelia-Remote-User``)."""

    proxy_header_name: str
    """Optional display-name header for the consent screen."""

    proxy_secret: str | None
    """Optional shared secret. If set, NPM must include it in the
    ``X-Internal-Auth-Proxy-Secret`` header on every /authorize request,
    or the request is rejected. Defense-in-depth against direct connections
    bypassing NPM."""

    cors_origins: tuple[str, ...]
    access_token_ttl: int
    refresh_token_ttl: int
    auth_code_ttl: int
    auth_request_ttl: int
    dcr_max_redirect_uris: int
    dcr_max_name_len: int
    dcr_max_body_bytes: int
    dcr_allow_http_redirects: bool
    """Allow http:// redirect URIs in DCR. Default false. Set true only for
    localhost development."""

    @classmethod
    def from_env(cls) -> AppConfig:
        issuer = _strip_or_none(os.environ.get("IDP_ISSUER"))
        if not issuer:
            raise RuntimeError("IDP_ISSUER is required")
        if not (issuer.startswith("http://") or issuer.startswith("https://")):
            raise RuntimeError("IDP_ISSUER must be an http(s) URL")
        issuer = issuer.rstrip("/")

        pepper = _load_secret("IDP_PEPPER")
        if not pepper or len(pepper) < 32:
            raise RuntimeError(
                "IDP_PEPPER must be set and at least 32 chars long. "
                "Generate with: openssl rand -hex 32"
            )

        resources_raw = _load_secret("IDP_RESOURCES") or os.environ.get(
            "IDP_RESOURCES", ""
        )
        resource_list = _split_csv(resources_raw)
        if not resource_list:
            raise RuntimeError(
                "IDP_RESOURCES must be set to a comma-separated allowlist of "
                "valid `resource` indicators (e.g. https://mcp-tcad.example). "
                "An empty allowlist would mean any token can be minted for any "
                "audience (RFC 9728 §7.4 confused-deputy)."
            )
        for r in resource_list:
            if not (r.startswith("https://") or r.startswith("http://")):
                raise RuntimeError(
                    f"IDP_RESOURCES entry {r!r} must be an http(s) URL"
                )

        return cls(
            issuer=issuer,
            db_path=os.environ.get("IDP_DB_PATH", "/data/db.sqlite"),
            keys_path=os.environ.get("IDP_KEYS_PATH", "/data/keys.json"),
            pepper=pepper,
            resource_allowlist=tuple(resource_list),
            proxy_header_user=os.environ.get(
                "IDP_PROXY_HEADER_USER", "X-Authelia-Remote-User"
            ),
            proxy_header_name=os.environ.get(
                "IDP_PROXY_HEADER_NAME", "X-Authelia-Remote-Name"
            ),
            proxy_secret=_load_secret("IDP_PROXY_SECRET"),
            cors_origins=tuple(
                _split_csv(
                    os.environ.get(
                        "IDP_CORS_ORIGINS",
                        "https://claude.ai,https://claude.com",
                    )
                )
            ),
            access_token_ttl=int(os.environ.get("IDP_ACCESS_TOKEN_TTL", "3600")),
            refresh_token_ttl=int(
                os.environ.get("IDP_REFRESH_TOKEN_TTL", str(30 * 24 * 3600))
            ),
            auth_code_ttl=int(os.environ.get("IDP_AUTH_CODE_TTL", "60")),
            auth_request_ttl=int(os.environ.get("IDP_AUTH_REQUEST_TTL", "600")),
            dcr_max_redirect_uris=int(
                os.environ.get("IDP_DCR_MAX_REDIRECT_URIS", "5")
            ),
            dcr_max_name_len=int(os.environ.get("IDP_DCR_MAX_NAME_LEN", "200")),
            dcr_max_body_bytes=int(
                os.environ.get("IDP_DCR_MAX_BODY_BYTES", str(8 * 1024))
            ),
            dcr_allow_http_redirects=(
                os.environ.get("IDP_DCR_ALLOW_HTTP_REDIRECTS", "false").lower()
                in ("true", "1", "yes", "on")
            ),
        )


# Convenience: namespaced field-default factories used by tests.
def _default_cors() -> tuple[str, ...]:  # pragma: no cover — only used as default
    return ("https://claude.ai", "https://claude.com")


__all__ = ["AppConfig", "_default_cors", "_load_secret", "_split_csv", "_strip_or_none"]
