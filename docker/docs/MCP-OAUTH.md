# MCP OAuth 2.1 setup (`mcp-tcad`)

> **Update (2026-05-12):** Most of this runbook is now superseded.
> **For Claude.ai integration, use [`MCP-IDP-SETUP.md`](MCP-IDP-SETUP.md)
> instead** — it walks through the new mcp-idp service that provides
> proper Dynamic Client Registration so Claude.ai's auto-discovery flow
> Just Works (no manual `client_id`/`secret` paste).
>
> The Authelia sections below remain accurate for the **OpenClaw
> client_credentials** path (§2.2 + §6) — OpenClaw still uses Authelia's
> OIDC provider directly with a static client. If you don't need that
> path either, you can skip this entire document.

This runbook covers the on-server steps to put **`mcp-tcad`** behind OAuth
2.1 / OIDC so Claude.ai's remote-MCP integration can use it. The static
bearer path stays available as a fallback for OpenClaw, Open WebUI, and
ad-hoc `curl` callers — both auth modes work in parallel.

The `tcad-mcp` server itself is **IdP-agnostic** (it speaks generic OIDC
discovery — no Authelia-specific code). This runbook configures Authelia
because that's what we already run; the same MCP container would work
unchanged behind Keycloak, Auth0, Okta, Dex, Authentik, Zitadel, or any
other OIDC-compliant authorization server. The contract any IdP must
satisfy is documented at the bottom under [Porting to another IdP](#porting-to-another-idp).

> **About Dynamic Client Registration (DCR).** The MCP spec describes an
> "automatic" UX where a client like Claude.ai discovers the IdP and
> registers itself via [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591)
> DCR. **Authelia does not support DCR** (confirmed against the [Authelia
> OIDC clients reference](https://www.authelia.com/configuration/identity-providers/openid-connect/clients/)
> and the still-open upstream discussion at
> [authelia/authelia#7304](https://github.com/authelia/authelia/discussions/7304)).
> Every OIDC client must be declared statically in `configuration.yml`.
> For Claude.ai that means pre-registering Claude as a static client in
> Authelia and entering the resulting `client_id` / `client_secret` in
> Claude.ai's integration UI manually. If you want true auto-discovery
> instead, switch IdPs — Keycloak, Authentik (≥ 2024.4), Auth0, Okta,
> and Zitadel all support DCR.

---

## 1. Verify Authelia version

**Prerequisite:** Authelia ≥ **4.39** for the current OIDC client schema
this runbook uses. Older versions still ship a working OIDC provider but
some client-config field names (e.g., `client_secret` plaintext vs. hashed,
JWKS configuration) have shifted. Check on the server:

```sh
ssh server 'docker inspect authelia --format "{{ .Config.Image }}"'
ssh server 'docker exec authelia authelia --version'
```

If older, bump the image tag in `compose.auth.yml` and `dcr authelia`.

---

## 2. Authelia OIDC provider config

All edits live in `${DATA}/authelia/config/configuration.yml` (gitignored
on the server). The file's structure is one giant document; the snippets
below show only the **`identity_providers.oidc`** subtree — find that
key in your existing config and merge the relevant pieces in. After
editing: `dcr authelia` to apply, then `docker logs authelia | tail -20`
to confirm clean startup (any schema error will be loud).

> **YAML caveat.** Authelia's OIDC schema has shifted across the 4.3x
> releases. The snippets below are written against 4.39+. Cross-check
> against the canonical [Authelia OIDC provider docs](https://www.authelia.com/configuration/identity-providers/openid-connect/provider/)
> and [Authelia OIDC client docs](https://www.authelia.com/configuration/identity-providers/openid-connect/clients/)
> for your version — especially the JWKS block, which has changed
> format more than once.

### 2.1 Enable OIDC + permit Claude.ai's CORS origin

If Authelia isn't already running an OIDC provider, generate a signing
keypair once:

```sh
ssh server '
  install -d -m 700 -o root -g root /srv/docker/data/authelia/keys
  docker exec authelia authelia crypto pair rsa generate \
    --directory /config/keys --file.private-key oidc.pem --file.public-key oidc.pub.pem
  echo "Generated /srv/docker/data/authelia/keys/oidc.pem (private) + oidc.pub.pem (public)"
'
```

Then in `identity_providers.oidc`:

```yaml
identity_providers:
  oidc:
    # Path inside the Authelia container; mount /srv/docker/data/authelia/keys
    # at /config/keys via compose.auth.yml.
    jwks:
      - key_id: oidc-rsa-1
        algorithm: RS256
        use: sig
        # Authelia 4.39+: either inline the PEM with a block scalar OR use a
        # file reference. The file-reference form is preferred so the secret
        # never lives in the YAML.
        key: |
          {{ fileContent "/config/keys/oidc.pem" | nindent 10 }}

    cors:
      endpoints:
        - authorization
        - token
        - revocation
        - introspection
        - userinfo
      allowed_origins:
        - https://claude.ai
        - https://claude.com

    # Two clients — see §2.2 (OpenClaw / CLI) and §2.3 (Claude.ai).
    clients:
      - client_id: openclaw-mcp
        # ... see §2.2 below
      - client_id: claude-mcp
        # ... see §2.3 below
```

`identity_providers.oidc.cors.allowed_origins` is required so Claude.ai's
browser can call back to Authelia's token / userinfo endpoints during
the consent flow. If your Authelia config has CORS configured elsewhere,
merge the `https://claude.ai` / `https://claude.com` entries into the
existing list.

### 2.2 Static client for OpenClaw + CLI (`client_credentials` grant)

For machine-to-machine clients (OpenClaw on the Pi, ad-hoc `curl`,
cron jobs). One client, all MCP audiences in its allowlist. Lives
inside `identity_providers.oidc.clients:`:

```yaml
clients:
  - client_id: openclaw-mcp
    client_name: OpenClaw MCP fleet
    # Generate with:
    #   docker exec authelia authelia crypto hash generate pbkdf2 \
    #     --variant sha512 --password "<cleartext>"
    # …and store the cleartext at ${DATA}/authelia/secrets/openclaw_oidc_secret
    # (mode 0600, owned by root) for pi/install-mcp-config.sh to ship to the Pi.
    # See §6.1 for the one-liner that does both.
    client_secret: '$pbkdf2-sha512$310000$...'
    public: false
    grant_types:
      - client_credentials
    # No redirect_uris — client_credentials doesn't redirect.
    scopes:
      - mcp:tcad
      # When other MCP servers grow OAuth, add more scopes here.
    audience:
      - https://mcp-tcad.danteb.com
    token_endpoint_auth_method: client_secret_post
    # client_credentials has no end user, so an authorization_policy isn't
    # meaningful here. Authelia treats the client itself as the principal.
```

### 2.3 Static client for Claude.ai (`authorization_code` grant)

**Authelia doesn't support DCR** (see the note at the top of this
runbook), so Claude.ai can't auto-register. Instead, we pre-register
Claude.ai as a static OIDC client here and paste the resulting
`client_id` + `client_secret` into Claude.ai's integration-setup UI by
hand.

```yaml
clients:
  - client_id: claude-mcp
    client_name: Claude.ai (mcp-tcad)
    # Generate the same way as the openclaw-mcp secret in §2.2, but a
    # separate value so Claude can be rotated independently. Store the
    # cleartext somewhere you can re-read it (a password manager) —
    # you'll paste it into Claude.ai during §5 setup.
    client_secret: '$pbkdf2-sha512$310000$...'
    public: false
    authorization_policy: two_factor
    consent_mode: explicit
    grant_types:
      - authorization_code
      - refresh_token
    response_types:
      - code
    response_modes:
      - query
    redirect_uris:
      # IMPORTANT: these are best-guess values. Anthropic doesn't publish a
      # stable list, and Claude.ai shows the redirect URI it actually wants
      # to use during the integration-setup flow (or in the error response
      # if the URI is wrong). Capture it from there and put the EXACT
      # value(s) here. Multiple are fine — list all the variants Claude
      # might use.
      - https://claude.ai/api/mcp/auth_callback
      - https://claude.com/api/mcp/auth_callback
    scopes:
      - openid
      - profile
      - mcp:tcad
    audience:
      - https://mcp-tcad.danteb.com
    token_endpoint_auth_method: client_secret_post
    # PKCE is required by RFC 9700 and the MCP authorization spec.
    require_pkce: true
    pkce_challenge_method: S256
```

If Claude.ai sends a redirect URI you haven't listed, Authelia logs
something like `invalid redirect_uri: <URL>`. Add that URL to
`redirect_uris:` and `dcr authelia` — that's the cleanest way to
discover the actual value Anthropic is using right now.

### 2.4 Apply

```sh
dcr authelia
docker logs authelia | tail -20    # confirm OIDC startup is clean
```

A clean start logs `Identity provider 'oidc' is enabled` and lists the
two clients (`openclaw-mcp`, `claude-mcp`). A misconfigured schema
prints a validation error and refuses to start the OIDC subsystem
(other Authelia features keep working).

---

## 3. NPM (no changes needed for the well-known)

NPM is a transparent reverse proxy under `mcp-tcad.danteb.com/...`, so the
`/.well-known/oauth-protected-resource` endpoint is reachable without any
extra config. Keep the existing settings:

- LAN+WG access list attached
- **Block Common Exploits OFF** — JWTs are large and may include `.` and
  base64 chars that BCE flags as suspicious
- WebSockets enabled (already on for MCP streamable-http)

The `mcp-tcad.danteb.com` host is already in the Authelia bypass rule for
`mcp.danteb.com` style hosts (the MCP server enforces auth itself). No
change needed.

---

## 4. HomeServer compose env vars

Already set in `docker/compose.mcp.yml` for the `mcp-tcad` service when
running v0.3.0+:

```yaml
environment:
  AUTH_TOKEN_FILE: /run/secrets/MCP_TOKEN_TCAD
  OAUTH_ISSUER: https://authelia.danteb.com
  OAUTH_AUDIENCE: https://mcp-tcad.danteb.com
  RESOURCE_URL: https://mcp-tcad.danteb.com
  OAUTH_REQUIRED_SCOPE: mcp:tcad
```

Both auth modes are auto-enabled because both their config keys are set.
v0.3.0+ adds explicit toggles you can set if you want to deviate from
that default:

| To do this | Add to compose env |
|---|---|
| Disable bearer (require OAuth for everyone — once OpenClaw migrates) | `BEARER_AUTH_ENABLED: 'false'` |
| Disable OAuth (revert to bearer-only) | `OAUTH_AUTH_ENABLED: 'false'` |
| Require both (force fail-fast at startup if either is misconfigured) | `BEARER_AUTH_ENABLED: 'true'` and `OAUTH_AUTH_ENABLED: 'true'` |

Leaving them unset (the current state) means each mode auto-detects from
its config presence — exact same behavior as v0.2.0.

To upgrade in place:

```sh
ssh server
z /srv/homeserver && git pull
z /srv/homeserver/docker
docker compose pull mcp-tcad
docker compose up -d mcp-tcad
docker logs mcp-tcad | tail -20
```

The container will start fine even if the Authelia OIDC config from §2
hasn't been applied yet — bearer requests still work; only OAuth requests
get a 503-ish response from the OIDC discovery cache (with negative-cache
backoff so the fetches don't storm).

---

## 5. Smoke tests

### Static bearer still works (most important regression check)

```sh
TOKEN=$(ssh server 'cat /srv/docker/data/mcp/secrets/MCP_TOKEN_TCAD')
curl -isk https://mcp-tcad.danteb.com/health
curl -isk -H "Authorization: Bearer $TOKEN" \
  https://mcp-tcad.danteb.com/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -20
```

### Resource metadata is discoverable

```sh
curl -sk https://mcp-tcad.danteb.com/.well-known/oauth-protected-resource | jq
```

Expected:

```json
{
  "resource": "https://mcp-tcad.danteb.com",
  "authorization_servers": ["https://authelia.danteb.com"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["mcp:tcad"]
}
```

### `client_credentials` grant (OpenClaw path)

```sh
SECRET=$(ssh server 'cat /srv/docker/data/authelia/secrets/openclaw_oidc_secret')
ACCESS_TOKEN=$(curl -sk -X POST https://authelia.danteb.com/api/oidc/token \
  -d "grant_type=client_credentials" \
  -d "client_id=openclaw-mcp" \
  -d "client_secret=$SECRET" \
  -d "scope=mcp:tcad" \
  -d "audience=https://mcp-tcad.danteb.com" | jq -r .access_token)
echo "$ACCESS_TOKEN" | head -c 60 ; echo
curl -isk -H "Authorization: Bearer $ACCESS_TOKEN" \
  https://mcp-tcad.danteb.com/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -20
```

Expected: `200 OK`. If you get `401`, the Authelia client config is wrong
(check audience binding) or the JWKS isn't being served (check
`https://authelia.danteb.com/jwks.json`).

### Claude.ai integration

Authelia doesn't support DCR (see top of this runbook), so Claude.ai
gets manually-pasted credentials instead of self-registering.

1. Confirm the `claude-mcp` static client from §2.3 exists in
   `${DATA}/authelia/config/configuration.yml` and Authelia restarted
   cleanly after `dcr authelia`.
2. In Claude.ai → Settings → Integrations → **Add custom integration**:
   - **Server URL:** `https://mcp-tcad.danteb.com`
   - **Name:** `TCAD`
3. Claude calls `/.well-known/oauth-protected-resource` → reads
   `authorization_servers: ["https://authelia.danteb.com"]` → calls
   `https://authelia.danteb.com/.well-known/openid-configuration`.
4. Because Authelia's discovery doc does NOT advertise a
   `registration_endpoint`, Claude.ai's flow falls back to asking you
   for credentials. The exact UX varies — most commonly Claude shows a
   "Use existing client" form. Paste:
   - **Client ID:** `claude-mcp`
   - **Client Secret:** the cleartext you generated for the `claude-mcp`
     client in §2.3 (NOT the `$pbkdf2-sha512$…` hashed form — that's
     what Authelia stores, but Claude.ai needs the cleartext for the
     `client_secret_post` token exchange).
5. Claude opens a popup to Authelia's authorize URL → you log in (2FA per
   the `two_factor` policy on `claude-mcp`) → consent → redirect back
   to Claude with an `code=` → Claude exchanges it for a JWT → first
   MCP call lands with `Authorization: Bearer <JWT>`.

**Common failure modes and where to look:**

| Symptom | Likely cause | Fix |
|---|---|---|
| Claude says "couldn't fetch the resource's authorization metadata" | `mcp-tcad.danteb.com/.well-known/oauth-protected-resource` returns 404 | OAuth is disabled — set `OAUTH_ISSUER` env var on `mcp-tcad` (§4). |
| Claude says "this resource doesn't support dynamic client registration; please paste credentials" | Expected — Authelia behavior | Paste `claude-mcp` credentials per step 4. |
| Authelia logs `invalid redirect_uri: <URL>` | Claude.ai's actual callback differs from what's in `claude-mcp.redirect_uris` | Capture the exact URL from the log and add it to §2.3, `dcr authelia`. |
| Authelia logs `invalid client_id` or `unauthorized_client` | Wrong client ID / secret pasted, or the secret hash in YAML doesn't match the cleartext you pasted | Re-generate the secret per §2.3's comment and re-paste both sides. |
| Token exchange succeeds but MCP returns 401 | `aud` mismatch | Check that `claude-mcp.audience` in §2.3 includes `https://mcp-tcad.danteb.com` exactly, and that `OAUTH_AUDIENCE` env var on `mcp-tcad` matches. |

If you'd rather have automatic discovery (no manual paste), swap
Authelia for an IdP that supports DCR — see [Porting to another IdP](#porting-to-another-idp).

---

## 6. OpenClaw on the Pi — wire it to Authelia for `mcp-tcad`

The Pi-hosted OpenClaw agent uses the OAuth `client_credentials` grant
against the same Authelia instance, with the static `openclaw-mcp`
client from §2.2. Three pieces:

### 6.1 Generate + store the OpenClaw OIDC client_secret on the server

Generate the secret pair (cleartext for the Pi, hashed for Authelia):

```sh
ssh server '
  set -e
  cleartext=$(openssl rand -hex 32)
  hashed=$(docker exec authelia authelia crypto hash generate pbkdf2 \
    --variant sha512 --password "$cleartext" | grep -oE "\$pbkdf2-sha512\$.*$")
  install -d -m 700 -o root -g root /srv/docker/data/authelia/secrets
  printf "%s" "$cleartext" | sudo install -m 600 -o root -g root /dev/stdin \
    /srv/docker/data/authelia/secrets/openclaw_oidc_secret
  echo "Cleartext stored at /srv/docker/data/authelia/secrets/openclaw_oidc_secret"
  echo "Paste this hashed value into the openclaw-mcp client in §2.2:"
  echo "$hashed"
'
```

Drop the `$pbkdf2-sha512$…` value into `client_secret:` for the
`openclaw-mcp` block in `${DATA}/authelia/config/configuration.yml`,
then `dcr authelia`.

### 6.2 Ship the cleartext to the Pi

Run the installer **from your dev machine** (the Pi is firewalled off
from the server by design — the dev machine is the trusted middleman):

```sh
cd /path/to/homeserver/pi
./install-mcp-config.sh pi
```

The installer reads:
- `${DATA}/mcp/secrets/MCP_TOKEN_*` — bearer tokens for the eight legacy
  MCP servers (openzim, wikipedia, etc.).
- `${DATA}/authelia/secrets/openclaw_oidc_secret` — the OpenClaw OIDC
  client_secret you just created.

…and writes `/etc/openclaw/mcp-clients.json` on the Pi with the OAuth
shape for `tcad` (and bearer shape for the other 8). The script runs
schema validation locally before shipping, so a typo in the sample is
caught before the file lands on the Pi.

If `openclaw_oidc_secret` doesn't exist yet, the installer prints a
warning and leaves the placeholder in place — the bearer-only servers
still install cleanly. Re-run after §6.1 lands.

### 6.3 OpenClaw application contract

What the OpenClaw app code on the Pi has to do for `auth.type ==
"oauth_client_credentials"` is documented in
[`pi/README.md`](../../pi/README.md#mcp-client-schema-what-the-openclaw-application-must-support).
Briefly: POST `grant_type=client_credentials` to the `token_url`, cache
the resulting access token until `now + expires_in - 60s`, send it as
`Authorization: Bearer …` on every MCP call, refresh on `401`. The
contract is filed for implementation in the OpenClaw repo — this
homeserver repo only ships the client config, not the app code.

### 6.4 Restart OpenClaw

Once §6.1–6.3 are in place:

```sh
ssh pi 'XDG_RUNTIME_DIR=/run/user/$(id -u openclaw) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u openclaw)/bus \
  sudo -u openclaw systemctl --user restart openclaw-gateway.service'
```

Then exercise the tcad MCP from a chat with the OpenClaw agent and
confirm via `docker logs mcp-tcad | tail -5` on the server that the
JWT-validated request landed.

### 6.5 Migration: bearer → OAuth-only on `mcp-tcad`

Once OpenClaw is reliably using the OAuth path, you can disable the
static-bearer fallback (no other consumer needs it). In
`docker/compose.mcp.yml`, add to the `mcp-tcad` env block:

```yaml
BEARER_AUTH_ENABLED: 'false'
```

Then `dcu` to recreate the container. Open WebUI's tcad integration (if
configured) breaks at this point — Open WebUI doesn't speak OAuth yet —
so don't disable the bearer until you're ready to drop or rework that
integration too. The static `MCP_TOKEN_TCAD` secret can also be deleted
once `BEARER_AUTH_ENABLED=false` is in effect.

---

## Porting to another IdP

The `tcad-mcp` container is OIDC-compliant — it doesn't care which IdP
issues the tokens. To run it against, e.g., Keycloak instead of Authelia:

1. Set `OAUTH_ISSUER=https://keycloak.example/realms/myrealm` in the
   compose env. That's it on the MCP-server side.
2. The IdP must:
   - serve `/.well-known/openid-configuration` with `jwks_uri` and
     `issuer` matching the configured issuer (OIDC §4.3)
   - support whichever grants you want (`client_credentials` for M2M,
     `authorization_code` + DCR for Claude.ai)
   - issue access tokens with `aud` containing your MCP server URL
3. (Optional) If the IdP doesn't ship discovery, set `OAUTH_JWKS_URL`
   directly and the MCP server will skip the discovery hop.

Asymmetric algorithms only (`RS256/RS384/RS512`, `PS256/PS384/PS512`,
`ES256/ES384/ES512`, `EdDSA`). HMAC tokens are rejected by the
allowlist as defense-in-depth against alg-confusion attacks.

---

## See also

- [tcad-mcp README — Authentication section](https://github.com/dantebarbieri/tcad-mcp#authentication) — three-mode framing (bearer / OAuth-manual / Automatic-discovery), env var reference.
- [tcad-mcp `docs/CLIENTS.md`](https://github.com/dantebarbieri/tcad-mcp/blob/main/docs/CLIENTS.md) — copy-paste setup for Claude.ai, Claude Desktop, ChatGPT, Cursor, Continue.dev, Open WebUI, Cody, Cline, Zed, plus `curl` / Python / TypeScript SDKs.
- [`pi/README.md`](../../pi/README.md) — OpenClaw client schema and the application contract for `auth.type == "oauth_client_credentials"`.
- [MCP authorization spec](https://modelcontextprotocol.io/specification/draft/basic/authorization)
- [RFC 9728 — OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728)
- [draft-ietf-oauth-resource-metadata](https://datatracker.ietf.org/doc/draft-ietf-oauth-resource-metadata/)
