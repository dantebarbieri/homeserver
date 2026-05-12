# mcp-idp

A tiny single-user OIDC IdP with **Dynamic Client Registration** (RFC 7591),
built specifically so [Claude.ai](https://claude.ai)'s remote-MCP "Custom
Integrations" feature can auto-register against a self-hosted homeserver.

## Why this exists

The MCP authorization spec specifies an "automatic" UX where a client like
Claude.ai discovers the IdP and registers itself via DCR. As of 2026 most
self-hosted OIDC servers (Authelia, Dex, Logto, Authentik) still don't ship
DCR, which forces users into manual `client_id` / `client_secret` paste.

This service plugs that gap with the smallest possible OIDC surface that
satisfies the MCP spec, RFC 7591 (DCR), and RFC 8707 (resource indicators).
**It is intentionally NOT a general-purpose IdP** — it's purpose-built for
MCP authorization on a single-user homeserver.

User authentication is delegated to an external auth proxy (in our case
[Authelia](https://www.authelia.com/) via NPM ForwardAuth), so this
container only handles OAuth/OIDC token issuance.

## Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/healthz` | GET | none | Container healthcheck |
| `/.well-known/openid-configuration` | GET | none | OIDC discovery doc |
| `/jwks.json` | GET | none | Public JWKS (token-validation keys) |
| `/register` | POST | none (open DCR; rate-limit at proxy) | RFC 7591 — client metadata in, `client_id`+`client_secret` out |
| `/authorize` | GET / POST | proxy headers (NPM → Authelia → forward `X-Authelia-Remote-User`) | Validate request, show consent, issue auth code |
| `/token` | POST | client auth (`client_secret_basic` or `client_secret_post`) | Exchange code or refresh token for access_token + id_token |
| `/revoke` | POST | client auth | RFC 7009 token revocation |

## What this server does NOT do

- User management (defer to your auth proxy: Authelia / Authentik / etc.)
- UserInfo endpoint (we put everything in the JWT)
- Implicit / password / client_credentials / device_code grants — only
  `authorization_code` (PKCE+S256 required) + `refresh_token`
- RFC 7592 client configuration management (no read/update/delete of
  registered clients via API)
- Federation / multi-tenant / orgs / RBAC / audit UI

## Configuration (env vars)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `IDP_ISSUER` | yes | — | Externally-visible URL (e.g. `https://mcp-idp.example`) |
| `IDP_DB_PATH` | no | `/data/db.sqlite` | SQLite database file |
| `IDP_KEYS_PATH` | no | `/data/keys.json` | JWKS-format keypair file (auto-generated on first start) |
| `IDP_PEPPER` / `IDP_PEPPER_FILE` | yes | — | 32+ byte secret for HMAC-hashing client secrets and tokens. Generate with `openssl rand -hex 32`. |
| `IDP_RESOURCES` / `IDP_RESOURCES_FILE` | yes | — | Comma-separated allowlist of valid `resource` indicators (e.g. `https://mcp-tcad.example,https://mcp-x.example`). Required at `/authorize`. |
| `IDP_PROXY_HEADER_USER` | no | `X-Authelia-Remote-User` | Request header to read the authenticated username from |
| `IDP_PROXY_HEADER_NAME` | no | `X-Authelia-Remote-Name` | Optional display-name header |
| `IDP_PROXY_SECRET` / `IDP_PROXY_SECRET_FILE` | no | unset | Optional shared secret in `X-Internal-Auth-Proxy-Secret` that NPM sends; rejects requests without it |
| `IDP_CORS_ORIGINS` | no | `https://claude.ai,https://claude.com` | Comma-separated allowed CORS origins |
| `IDP_ACCESS_TOKEN_TTL` | no | `3600` | Access-token TTL (seconds) |
| `IDP_REFRESH_TOKEN_TTL` | no | `2592000` | Refresh-token TTL (seconds, 30 days) |
| `IDP_AUTH_CODE_TTL` | no | `60` | Auth-code TTL (seconds) |
| `IDP_AUTH_REQUEST_TTL` | no | `600` | Server-side auth-transaction TTL between GET and POST `/authorize` (seconds) |
| `IDP_DCR_MAX_REDIRECT_URIS` | no | `5` | DCR redirect-URI count cap |
| `IDP_DCR_MAX_NAME_LEN` | no | `200` | DCR `client_name` length cap |

Long-lived secrets follow the standard `ENV_VAR` / `ENV_VAR_FILE` pattern
(direct env wins over file).

## Running locally

```bash
docker run --rm -p 8080:8080 \
  -e IDP_ISSUER="http://localhost:8080" \
  -e IDP_PEPPER="$(openssl rand -hex 32)" \
  -e IDP_RESOURCES="https://mcp-tcad.example" \
  -e IDP_PROXY_HEADER_USER="X-Test-User" \
  -v mcp-idp-data:/data \
  ghcr.io/example/mcp-idp:latest
```

## HomeServer integration

This service is built and deployed from the homeserver monorepo
(`docker/dockerfiles/mcp-idp/`). It's wired into `compose.auth.yml` as the
`mcp-idp` service and reaches the public internet via NPM at
`mcp-idp.danteb.com`.

**End-to-end setup runbook:** [`docker/docs/MCP-IDP-SETUP.md`](../../docs/MCP-IDP-SETUP.md)
walks through the ~20-minute deployment from a clean homeserver to a
working Claude.ai integration: secret bootstrap, NPM proxy host with
per-path Authelia ForwardAuth, `mcp-tcad` re-pointing, Claude.ai setup,
plus smoke tests, troubleshooting, and maintenance procedures.

The runbook references two NPM snippet files that are already on the
production server (per `production-configs/README.md`):

- `/snippets/authelia-authrequest.conf` — internal location handler
- `/snippets/authelia-location.conf` — drop-in include for protected paths

If your deployment doesn't have these (or you're running this container
elsewhere), see the [Authelia NPM integration docs](https://www.authelia.com/integration/proxies/nginx-proxy-manager/)
for the canonical content.


