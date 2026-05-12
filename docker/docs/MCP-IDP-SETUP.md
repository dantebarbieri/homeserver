# Setting up mcp-idp on the homeserver

End-to-end runbook for getting Claude.ai (and any other DCR-capable MCP
client) talking to your homeserver MCP servers via [`mcp-idp`](../dockerfiles/mcp-idp/README.md).
~20 minutes from a clean homeserver to a working integration.

---

## What you'll get

- A new container `mcp-idp` running at `https://mcp-idp.danteb.com`
- Claude.ai's "Custom Integrations" feature works **automatically** — paste
  `https://mcp-tcad.danteb.com`, click Connect, log into Authelia (with
  your existing 2FA), approve the consent screen, done. Claude registers
  itself dynamically (DCR), gets an OAuth token, and starts using the MCP.
- The same flow works for any future MCP server you add to the
  `IDP_RESOURCES` allowlist.
- The static-bearer fallback on `mcp-tcad` keeps working unchanged for
  OpenClaw / Open WebUI / `curl`.

```
                  ┌──────────────┐
                  │  Claude.ai   │
                  │   browser    │
                  └──────┬───────┘
                         │ 1. paste URL
                         │ 2. discover
                         ▼
        ┌────────────────────────────────┐
        │   mcp-tcad.danteb.com          │
        │   (the MCP server you want)    │ ← validates Bearer JWT against
        └────────────────────────────────┘    mcp-idp's JWKS
                         │
                         │ 3. /.well-known/oauth-protected-resource
                         │    → "use mcp-idp.danteb.com"
                         ▼
        ┌────────────────────────────────┐
        │   mcp-idp.danteb.com           │
        │   (DCR + token issuer)         │
        └────────────────┬───────────────┘
                         │ 4. /authorize routed via NPM ForwardAuth
                         ▼
        ┌────────────────────────────────┐
        │   authelia.danteb.com          │ ← 2FA login (existing)
        │   (user authentication)        │
        └────────────────────────────────┘
```

---

## Prerequisites

Before starting:

- [x] Homeserver clone is up to date (`git pull` on the server)
- [x] Authelia is running and healthy (you can log in to any Authelia-protected service)
- [x] NPM is running with the existing snippets in
      `${DATA}/nginxproxymanager/snippets/` (specifically
      `authelia-authrequest.conf` + `authelia-location.conf` — verify
      one of your existing Authelia-protected proxy hosts works)
- [x] `mcp-tcad` is already deployed (currently behind static-bearer auth)
- [x] You have admin access to NPM's web UI

If any are missing, fix them first — this runbook assumes the standard
homeserver baseline.

---

## Step 1: Bootstrap `mcp-idp` on the server (~5 min)

SSH to the server.

```sh
ssh server
z /srv/homeserver
git pull
z /srv/homeserver/docker
```

### 1.1 Generate the long-lived secrets

`IDP_PEPPER` HMACs every stored secret (client_secrets, auth codes,
refresh tokens). `IDP_PROXY_SECRET` is the shared header NPM sends to
prove a request came through the proxy (defense-in-depth on `/authorize`).

```sh
sudo install -d -o root -g root -m 700 /srv/docker/data/mcp-idp/secrets
sudo install -d -o "$(id -u)":"$(id -g)" -m 700 /srv/docker/data/mcp-idp

openssl rand -hex 32 | sudo tee /srv/docker/data/mcp-idp/secrets/IDP_PEPPER >/dev/null
openssl rand -hex 32 | sudo tee /srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET >/dev/null
sudo chmod 600 /srv/docker/data/mcp-idp/secrets/IDP_*

# Print the proxy secret — you'll paste it into NPM in Step 2.4.
sudo cat /srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET
```

> **Back up `IDP_PEPPER`.** Losing it permanently invalidates every issued
> token (and breaks every refresh token). Store a copy in your password
> manager.

### 1.2 Build + start the container

```sh
docker compose build mcp-idp
docker compose up -d mcp-idp
docker logs mcp-idp | tail -20
```

Expected log lines:

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

If you see a startup error, check the env vars in `compose.auth.yml` and
the secret files exist with the right perms.

### 1.3 Verify the keypair was generated

```sh
sudo ls -l /srv/docker/data/mcp-idp/
# Expected:
#   db.sqlite      <- created on first DB write
#   keys.json      <- the RSA keypair (back this up!)
#   secrets/

sudo head -c 200 /srv/docker/data/mcp-idp/keys.json
# Should show: { "keys": [ { "kty": "RSA", "kid": "k...", ... } ] }
```

> **Back up `keys.json`.** Same reason as the pepper — losing it
> invalidates every issued token. Both files together are all you need
> to migrate mcp-idp to a new host or rebuild after disaster.

### 1.4 Smoke test from inside the proxy network

```sh
# Should print "ok"
docker exec -it nginxproxymanager curl -s http://mcp-idp:8080/healthz

# Should print the JSON discovery doc
docker exec -it nginxproxymanager curl -s http://mcp-idp:8080/.well-known/openid-configuration | python3 -m json.tool
```

Container is up. Move to NPM.

---

## Step 2: Set up the NPM proxy host (~10 min)

The MCP-IDP host is unusual: most paths must be reachable WITHOUT auth
(Claude.ai's servers call `/.well-known/...`, `/jwks.json`, `/register`,
`/token` directly), but `/authorize` MUST be Authelia-protected (this is
where the user logs in to grant consent).

NPM supports this via **Custom Locations**: the host has no Authelia
ForwardAuth at the root, and we add one Custom Location for `/authorize`
that includes the Authelia snippets.

### 2.1 Create the proxy host

In NPM → **Hosts → Proxy Hosts → Add Proxy Host**:

| Tab | Field | Value |
|---|---|---|
| **Details** | Domain Names | `mcp-idp.danteb.com` |
| **Details** | Scheme | `http` |
| **Details** | Forward Hostname / IP | `mcp-idp` |
| **Details** | Forward Port | `8080` |
| **Details** | Cache Assets | off |
| **Details** | Block Common Exploits | **off** (JWTs trip BCE) |
| **Details** | Websockets Support | on |
| **Custom Locations** | _empty for now — added in 2.4_ | |
| **SSL** | SSL Certificate | Request a new SSL Certificate (Let's Encrypt) |
| **SSL** | Force SSL | on |
| **SSL** | HTTP/2 Support | on |
| **SSL** | HSTS Enabled | on |
| **Access List** | Access List | _none_ (this host needs to be reachable from Claude.ai's IPs) |
| **Advanced** | Custom Nginx Configuration | _see 2.2 below_ |

### 2.2 Main Advanced tab — register the Authelia internal location

Paste into the **Advanced → Custom Nginx Configuration** field:

```nginx
# Hidden internal location used by the auth_request directive in §2.4.
# This is what Authelia's NPM-integration snippet expects.
include /snippets/authelia-authrequest.conf;

# Belt-and-braces: deny anything outside the documented endpoints.
# Comment this out during initial bring-up if Claude.ai uses a path you
# didn't anticipate; check Authelia logs for the unmocked URL.
location = /healthz                                 { proxy_pass http://mcp-idp:8080; }
location = /.well-known/openid-configuration         { proxy_pass http://mcp-idp:8080; }
location = /.well-known/oauth-authorization-server   { proxy_pass http://mcp-idp:8080; }
location = /jwks.json                                { proxy_pass http://mcp-idp:8080; }
location = /register                                 { proxy_pass http://mcp-idp:8080; }
location = /token                                    { proxy_pass http://mcp-idp:8080; }
location = /revoke                                   { proxy_pass http://mcp-idp:8080; }
# /authorize lives in Custom Locations (§2.4) so it can include the
# Authelia ForwardAuth snippet without affecting the open endpoints.
```

> The hidden `location = /internal/authelia/authz` block lives inside
> `authelia-authrequest.conf` (already on the server per
> `production-configs/README.md`). The `include` directive at the top
> brings it into this proxy host's scope so the auth_request directive
> in §2.4 can find it.

### 2.3 Save the proxy host

Click **Save**. NPM provisions a Let's Encrypt cert for
`mcp-idp.danteb.com`. (You may need to wait 30 seconds and refresh.)

Verify the cert is live:

```sh
curl -sI https://mcp-idp.danteb.com/healthz | head -3
# Expected: HTTP/2 200
```

### 2.4 Add the `/authorize` Custom Location

Reopen the proxy host → **Custom Locations** tab → **Add Location**:

| Field | Value |
|---|---|
| Define location | `/authorize` |
| Scheme | `http` |
| Forward Hostname / IP | `mcp-idp` |
| Forward Port | `8080` |

Click the **Advanced** (gear) icon for this location and paste:

```nginx
# Authelia ForwardAuth — gates the consent screen behind your Authelia 2FA.
include /snippets/authelia-location.conf;

# Defense-in-depth shared secret. mcp-idp will reject any /authorize
# request that doesn't carry this header (so direct connections that
# bypass NPM can't reach the consent flow).
#
# Replace YOUR_PROXY_SECRET_HERE with the cleartext value of
# /srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET (printed in §1.1).
proxy_set_header X-Internal-Auth-Proxy-Secret "YOUR_PROXY_SECRET_HERE";
```

Click **Save**.

### 2.5 Verify the per-path gating

```sh
# Open endpoints — no auth required.
curl -sI https://mcp-idp.danteb.com/.well-known/openid-configuration | head -1
# Expected: HTTP/2 200

curl -sI https://mcp-idp.danteb.com/jwks.json | head -1
# Expected: HTTP/2 200

# /authorize without Authelia session — Authelia redirects to its login.
curl -sI 'https://mcp-idp.danteb.com/authorize?response_type=code&client_id=test' | head -3
# Expected: HTTP/2 302 with `location: https://authelia.danteb.com/?rd=...`
```

If the third curl returns 401 instead of 302, the Authelia snippet path
in `authelia-location.conf` doesn't match your install — verify it
points at `http://authelia:9091/api/authz/auth-request`.

---

## Step 3: Re-point `mcp-tcad` (already done in compose; verify)

The compose change has already been committed in `docker/compose.mcp.yml`
— the `mcp-tcad` service now sets `OAUTH_ISSUER=https://mcp-idp.danteb.com`.
Apply it on the server:

```sh
z /srv/homeserver/docker
git pull   # if you haven't already
docker compose pull mcp-tcad   # in case the GHCR image was bumped
docker compose up -d mcp-tcad
docker logs mcp-tcad | tail -10
```

Verify the resource-metadata endpoint now lists mcp-idp as the
authorization server:

```sh
curl -s https://mcp-tcad.danteb.com/.well-known/oauth-protected-resource | python3 -m json.tool
# Expected:
# {
#   "resource": "https://mcp-tcad.danteb.com",
#   "authorization_servers": ["https://mcp-idp.danteb.com"],
#   "bearer_methods_supported": ["header"]
# }
```

The static-bearer fallback still works — verify with your existing
`MCP_TOKEN_TCAD`:

```sh
TOKEN=$(sudo cat /srv/docker/data/mcp/secrets/MCP_TOKEN_TCAD)
curl -s -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     https://mcp-tcad.danteb.com/mcp | head -c 200
# Expected: JSON-RPC response listing the tcad tools
```

---

## Step 4: Add the integration in Claude.ai (~2 min)

In Claude.ai (web):

1. Click your name (bottom-left) → **Settings** → **Integrations**.
2. Click **Add custom integration**.
3. Fill in:
   - **Name:** `TCAD`
   - **Server URL:** `https://mcp-tcad.danteb.com`
4. Click **Add**, then **Connect**.
5. A popup opens to `mcp-idp.danteb.com/authorize` → which Authelia
   intercepts → log in with your usual Authelia credentials + 2FA.
6. After Authelia, the mcp-idp consent page appears: *"Claude.ai wants to
   access your homeserver — Resource: https://mcp-tcad.danteb.com — Scope:
   (none requested) — [Approve] [Deny]"*. Click **Approve**.
7. The popup closes. The integration shows as connected in Claude.ai.

In any new conversation, the TCAD tools (`search_property`,
`get_property_general`, etc.) are available. Try asking: *"Look up
11301 Maidenstone Dr in TCAD."*

---

## Adding more MCP servers later

When you add a second OAuth-aware MCP server (say `mcp-foo.danteb.com`):

1. **Allowlist its URL on `mcp-idp`.** Edit `compose.auth.yml`:
   ```yaml
   mcp-idp:
     environment:
       IDP_RESOURCES: https://mcp-tcad.danteb.com,https://mcp-foo.danteb.com
   ```
   Then `docker compose up -d mcp-idp`.

2. **Configure the new MCP server to validate against `mcp-idp`.** Set in
   the new server's compose env:
   ```yaml
   OAUTH_ISSUER: https://mcp-idp.danteb.com
   OAUTH_AUDIENCE: https://mcp-foo.danteb.com
   RESOURCE_URL: https://mcp-foo.danteb.com
   ```
   The MCP server discovers mcp-idp's JWKS automatically and starts
   accepting tokens. No code changes needed (provided the MCP server
   speaks generic OIDC; tcad-mcp v0.2.0+ does).

3. **No changes to mcp-idp's NPM proxy host or Authelia config** — same
   IdP serves all your MCP servers.

4. **In Claude.ai**, add it as a separate Custom Integration with the
   new MCP server's URL. The flow is identical to Step 4 above.

---

## Smoke tests (full token-exchange round trip)

For the truly paranoid — a manual `curl` walkthrough of every step
Claude.ai automates.

```sh
# 1. Discover the MCP server's authorization server.
curl -s https://mcp-tcad.danteb.com/.well-known/oauth-protected-resource

# 2. Discover the AS endpoints.
curl -s https://mcp-idp.danteb.com/.well-known/openid-configuration | python3 -m json.tool

# 3. Register a new client via DCR (no auth required).
CLIENT_RESPONSE=$(curl -s -X POST https://mcp-idp.danteb.com/register \
  -H 'Content-Type: application/json' \
  -d '{
    "client_name": "smoke-test",
    "redirect_uris": ["https://example.com/cb"],
    "grant_types": ["authorization_code", "refresh_token"]
  }')
echo "$CLIENT_RESPONSE" | python3 -m json.tool
# Save:
CLIENT_ID=$(echo "$CLIENT_RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["client_id"])')
CLIENT_SECRET=$(echo "$CLIENT_RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["client_secret"])')

# 4. (Manual.) /authorize requires a browser session — paste the URL into
#    a browser, log into Authelia, approve, capture the `code=...` param
#    that Claude would receive.
echo "Open: https://mcp-idp.danteb.com/authorize?response_type=code&client_id=$CLIENT_ID&redirect_uri=https%3A%2F%2Fexample.com%2Fcb&state=test&code_challenge=GENERATE_S256_OF_VERIFIER&code_challenge_method=S256&resource=https%3A%2F%2Fmcp-tcad.danteb.com"
# Capture code= from the redirect URL.

# 5. Exchange code for tokens.
# (use the verifier matching the challenge above; for SHA256 of "abc": CODE_VERIFIER=abc)
curl -s -X POST https://mcp-idp.danteb.com/token \
  -d "grant_type=authorization_code" \
  -d "code=PASTE_CODE_HERE" \
  -d "redirect_uri=https://example.com/cb" \
  -d "code_verifier=PASTE_VERIFIER_HERE" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" | python3 -m json.tool

# 6. Use the access_token against the MCP server.
curl -s -H "Authorization: Bearer PASTE_ACCESS_TOKEN_HERE" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     https://mcp-tcad.danteb.com/mcp | python3 -m json.tool
```

If steps 1–6 all succeed, Claude.ai will Just Work.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `503` on `https://mcp-idp.danteb.com/healthz` | container not running or wrong Forward Hostname in NPM | `docker logs mcp-idp` + verify NPM Details tab points at `mcp-idp:8080` |
| `200` on open endpoints, `401` on `/authorize` | The Authelia ForwardAuth snippet in §2.4 wasn't applied | Reopen the Custom Location, re-paste the snippet, hit Save |
| `403 Forbidden` on `/authorize` even after Authelia login | Wrong / missing `IDP_PROXY_SECRET` value in the `proxy_set_header` line | Re-read `/srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET` and paste the EXACT value (no quotes within quotes) |
| Claude.ai's "Connect" hangs forever | CORS — Claude's browser can't reach `/.well-known/...` due to CORS | Verify `IDP_CORS_ORIGINS` in `compose.auth.yml` includes `https://claude.ai,https://claude.com`. `dcr mcp-idp` after change. |
| Authelia logs `invalid redirect_uri` after Claude registers | Claude is using a redirect URI Authelia doesn't allow (only an issue if you've added Authelia's own validation — mcp-idp doesn't restrict per-client) | Not applicable to mcp-idp; if you see this, you're hitting Authelia, not mcp-idp |
| `mcp-idp` logs `Invalid resource: 'https://...'` | Claude's `resource` param is not in `IDP_RESOURCES` | Add the URL to `IDP_RESOURCES` and `dcr mcp-idp` |
| Tokens stop working after a `mcp-idp` restart | `${DATA}/mcp-idp/keys.json` was lost or regenerated | Restore from backup. If no backup, every existing client must re-DCR-register and re-auth in Claude.ai. |
| `mcp-tcad` logs `audience mismatch` after switching `OAUTH_ISSUER` | The `aud` on tokens issued by mcp-idp doesn't match `OAUTH_AUDIENCE` on mcp-tcad | Both must be `https://mcp-tcad.danteb.com`. Check both env blocks. |

For deeper diagnosis: `docker logs mcp-idp -f` while reproducing.

---

## Maintenance

### Backup what matters

Two files are the entire critical state:

```sh
sudo tar -czf mcp-idp-backup-$(date +%F).tgz -C /srv/docker/data/mcp-idp \
  keys.json db.sqlite secrets/
```

Keep this somewhere safe. `keys.json` and `secrets/IDP_PEPPER` are the
only things you can't recreate.

### Rotate `IDP_PROXY_SECRET`

```sh
openssl rand -hex 32 | sudo tee /srv/docker/data/mcp-idp/secrets/IDP_PROXY_SECRET >/dev/null
docker compose restart mcp-idp
# Then update the proxy_set_header value in NPM Custom Location §2.4 and Save.
```

### Rotate the JWT signing keypair

There's no automatic rotation. If you suspect compromise:

```sh
sudo cp /srv/docker/data/mcp-idp/keys.json /srv/docker/data/mcp-idp/keys.json.old
sudo rm /srv/docker/data/mcp-idp/keys.json
docker compose restart mcp-idp
# A fresh keypair is generated. All existing tokens (access + refresh)
# become invalid; users must re-auth in Claude.ai.
```

For zero-downtime rotation, manually edit `keys.json` to add a new
RSA key as the FIRST entry (active signer) while keeping the old key
in the array for verification grace. After all access tokens expire
(default 1h), remove the old key from the array.

### View what's been issued

```sh
sudo sqlite3 /srv/docker/data/mcp-idp/db.sqlite \
  'SELECT client_id, client_name, registered_at FROM clients ORDER BY registered_at DESC;'

sudo sqlite3 /srv/docker/data/mcp-idp/db.sqlite \
  'SELECT client_id, sub, scope, resource, issued_at, revoked_at FROM refresh_tokens;'
```

### Revoke a client

```sh
# Find the client_id from the query above.
sudo sqlite3 /srv/docker/data/mcp-idp/db.sqlite \
  "DELETE FROM clients WHERE client_id = 'dcr-XXXXX';"
sudo sqlite3 /srv/docker/data/mcp-idp/db.sqlite \
  "DELETE FROM refresh_tokens WHERE client_id = 'dcr-XXXXX';"
```

Already-issued JWT access tokens stay valid until their `exp` (default 1h)
because they're stateless. To force immediate invalidation: rotate the
JWT signing key (above).

### Logs

```sh
docker logs mcp-idp --tail 100 -f
```

---

## Other clients (Cursor, Claude Desktop, ChatGPT, etc.)

The Claude.ai walkthrough in §4 is the simplest case (full DCR auto-flow).
For other MCP-aware clients see [`tcad-mcp/docs/CLIENTS.md`](https://github.com/dantebarbieri/tcad-mcp/blob/main/docs/CLIENTS.md)
— it covers Claude Desktop, Cursor, Continue.dev, Open WebUI, Cody,
Cline, Zed, ChatGPT (via OpenAPI bridge), and `curl` / Python /
TypeScript SDK examples.

For clients that **don't** support DCR (older versions, restrictive IDEs),
you can still use mcp-idp by manually completing one DCR call yourself
(see §"Smoke tests" step 3) and pasting the resulting `client_id` /
`client_secret` into the client's config. Once registered, the client
behaves identically.

---

## See also

- [`docker/dockerfiles/mcp-idp/README.md`](../dockerfiles/mcp-idp/README.md) — the project README (architecture, env vars, threat model)
- [`docker/dockerfiles/mcp-idp/mcp_idp/`](../dockerfiles/mcp-idp/mcp_idp/) — source code
- [`docker/docs/MCP-OAUTH.md`](MCP-OAUTH.md) — the original Authelia-only runbook (now superseded for Claude.ai; still useful for OpenClaw / `client_credentials`)
- [`pi/README.md`](../../pi/README.md) — OpenClaw schema + installer
- [Authelia NPM integration docs](https://www.authelia.com/integration/proxies/nginx-proxy-manager/)
- [MCP authorization spec](https://modelcontextprotocol.io/specification/draft/basic/authorization)
- [RFC 7591 (Dynamic Client Registration)](https://datatracker.ietf.org/doc/html/rfc7591)
- [RFC 9728 (OAuth 2.0 Protected Resource Metadata)](https://www.rfc-editor.org/rfc/rfc9728)
