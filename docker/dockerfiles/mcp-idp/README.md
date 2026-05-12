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

### One-time bootstrap (on the server)

```sh
# 1. Create the data + secrets dirs.
sudo install -d -o root -g root -m 700 /srv/docker/data/mcp-idp/secrets
sudo install -d -o $UID:$GID -m 700 /srv/docker/data/mcp-idp

# 2. Generate the long-lived secrets.
openssl rand -hex 32 | sudo tee /srv/docker/data/mcp-idp/secrets/IDP_PEPPER >/dev/null
openssl rand -hex 32 | sudo tee /srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET >/dev/null
sudo chmod 600 /srv/docker/data/mcp-idp/secrets/IDP_*

# 3. Build + start the container.
cd /srv/homeserver/docker
docker compose pull mcp-idp || docker compose build mcp-idp
docker compose up -d mcp-idp
docker logs mcp-idp | tail -10
```

The first start auto-generates the RSA signing keypair at `/data/keys.json`
(persisted in the `${DATA}/mcp-idp/` volume). Back this up — losing it
invalidates every issued token.

### NPM proxy host (`mcp-idp.danteb.com`)

The wiring matters because user authentication is delegated to Authelia
via NPM ForwardAuth, but only on `/authorize`. Other paths must be
reachable without ForwardAuth so Claude.ai's servers can call them.

In NPM:

1. Create a new **Proxy Host** with **Hostname** `mcp-idp.danteb.com`,
   **Forward Hostname** `mcp-idp`, **Forward Port** `8080`. Enable
   WebSockets, **leave Block Common Exploits OFF** (JWTs trip BCE).
2. Add a new **Custom Location** for path `/authorize`:
   - Forward to the same `mcp-idp:8080`
   - In the **Advanced** tab for this location:
     ```nginx
     include /snippets/authelia_forwardauth.conf;
     proxy_set_header X-Internal-Auth-Proxy-Secret "<paste IDP_PROXY_SECRET cleartext here>";
     ```
3. Get the **DNS** record. `mcp-idp.danteb.com` resolves automatically via
   the existing `*.danteb.com` wildcard CNAME — no Cloudflare changes needed.

Optional belt-and-braces: in the proxy host's main **Advanced** tab,
`deny all` for any path that isn't in your "discovery + DCR + token" list.
The IdP's own validation already protects the surface but path-level
NPM allowlisting is a free extra layer.

### Add an MCP server to the IdP's resource allowlist

`IDP_RESOURCES` in `compose.auth.yml` controls which RFC 8707 `resource`
values the IdP will accept at `/authorize` and which `aud` claim it will
mint. To add a new MCP server (say `mcp-foo.danteb.com`):

```yaml
# compose.auth.yml
mcp-idp:
  environment:
    IDP_RESOURCES: https://mcp-tcad.danteb.com,https://mcp-foo.danteb.com
```

Then `dcr mcp-idp`. Existing tokens are unaffected.

### Pointing an MCP server at this IdP

Set the MCP server's OAuth env vars to point here:

```yaml
# in your MCP server's compose env
OAUTH_ISSUER: https://mcp-idp.danteb.com
OAUTH_AUDIENCE: https://your-mcp.danteb.com
RESOURCE_URL: https://your-mcp.danteb.com
```

The MCP server discovers `/.well-known/openid-configuration`, fetches the
JWKS, validates incoming JWTs against it. No changes to the MCP server
code itself (provided it speaks generic OIDC; tcad-mcp v0.2.0+ does).

### Adding the integration in Claude.ai

1. Settings → Integrations → **Add custom integration**
2. **Server URL:** `https://your-mcp.danteb.com` (the MCP server URL,
   NOT mcp-idp's URL)
3. Click **Connect**.
4. Claude follows the discovery → DCR → consent chain automatically.
   You'll be redirected to `mcp-idp.danteb.com/authorize` (which sends
   you through Authelia's 2FA login first), then to the consent page,
   then back to Claude with a token.

### Troubleshooting

| Symptom | Look at |
|---|---|
| `403` on `/authorize` | NPM Custom Location is missing `proxy_set_header X-Internal-Auth-Proxy-Secret` or the value doesn't match the secret file |
| `401 Authentication required` on `/authorize` | NPM Custom Location is missing `include /snippets/authelia_forwardauth.conf` |
| `Invalid resource` on `/authorize` | The MCP server's `RESOURCE_URL` isn't in `IDP_RESOURCES` |
| Claude.ai integration setup hangs | Check CORS — `IDP_CORS_ORIGINS` must include `https://claude.ai` |
| Tokens stop working after a restart | `${DATA}/mcp-idp/keys.json` was lost — back it up. Restart Claude integrations to re-auth. |


