# MCP OAuth 2.1 setup (`mcp-tcad`)

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

---

## 1. Verify Authelia version

**Prerequisite:** Authelia ≥ **4.39** for Dynamic Client Registration
(DCR), which is what Claude.ai uses to register itself as an OAuth client
on first use. Check on the server:

```sh
ssh server 'docker inspect authelia --format "{{ .Config.Image }}"'
ssh server 'docker exec authelia authelia --version'
```

If older, bump the image tag in `compose.auth.yml` and `dcr authelia`.
DCR is enabled by default in 4.39+ if you also enable the OIDC provider.

---

## 2. Authelia OIDC provider config

All edits live in `${DATA}/authelia/config/configuration.yml` (gitignored
on the server). After editing: `dcr authelia` to apply.

### 2.1 Enable OIDC + permit Claude.ai's CORS origin

```yaml
identity_providers:
  oidc:
    # Generated once: `authelia crypto pair rsa generate --directory /config/keys`
    jwks:
      - key: {{ secret "/config/secrets/oidc.private.pem" | mindent 10 "|" | msquote }}

    # Authelia signs ID tokens / access tokens with this issuer URL. Must
    # match what the MCP server sees in the JWT `iss` claim.
    # (Defaults to https://authelia.danteb.com — set explicitly to be safe.)

    cors:
      endpoints: [token, revocation, introspection, userinfo]
      allowed_origins:
        - https://claude.ai

    # ↓ The two clients we add below.
    clients:
      - client_id: openclaw-mcp
        # ... see §2.2

    # Dynamic Client Registration — Claude.ai self-registers via this.
    authorization_policies:
      mcp_users:
        default_policy: two_factor
        rules:
          - subject: 'group:admins'
            policy: one_factor
```

### 2.2 Static client for OpenClaw + CLI (`client_credentials` grant)

For machine-to-machine clients (OpenClaw on the Pi, ad-hoc `curl`,
cron jobs). One client, all MCP audiences in its allowlist:

```yaml
clients:
  - client_id: openclaw-mcp
    client_name: OpenClaw MCP fleet
    # Generate with: `authelia crypto hash generate pbkdf2 --variant sha512 --random --random.length 64`
    # Store the cleartext value in ${DATA}/authelia/secrets/openclaw_oidc_secret
    # (mode 0600, owned by root) for `pi/install-mcp-config.sh` to ship to the Pi.
    client_secret: '$pbkdf2-sha512$310000$...'
    public: false
    authorization_policy: mcp_users
    grant_types:
      - client_credentials
    scopes:
      - mcp:tcad
      # When other MCP servers grow OAuth, add more scopes here.
    audience:
      - https://mcp-tcad.danteb.com
    token_endpoint_auth_method: client_secret_post
```

### 2.3 DCR template for Claude.ai (`authorization_code` grant)

Claude.ai's remote-MCP integration self-registers on first use via DCR.
The template defines the policy applied to all dynamically-registered
clients whose redirect URIs match the Claude.ai allowlist:

```yaml
client_registration:
  enabled: true
  default_policy: two_factor
  allowed_redirect_uris:
    # Verify this list against Claude.ai's current docs before relying on it.
    - https://claude.ai/api/mcp/auth_callback
    - https://claude.com/api/mcp/auth_callback
  allowed_grant_types:
    - authorization_code
    - refresh_token
  allowed_response_types:
    - code
  allowed_token_endpoint_auth_methods:
    - client_secret_post
    - client_secret_basic
  allowed_scopes:
    - mcp:tcad
    - openid
    - profile
  default_audience:
    - https://mcp-tcad.danteb.com
```

### 2.4 Apply

```sh
dcr authelia
docker logs authelia | tail -20    # confirm OIDC startup is clean
```

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
running v0.2.0+:

```yaml
environment:
  AUTH_TOKEN_FILE: /run/secrets/MCP_TOKEN_TCAD
  OAUTH_ISSUER: https://authelia.danteb.com
  OAUTH_AUDIENCE: https://mcp-tcad.danteb.com
  RESOURCE_URL: https://mcp-tcad.danteb.com
  OAUTH_REQUIRED_SCOPE: mcp:tcad
```

The bearer path (`AUTH_TOKEN_FILE`) keeps working unchanged. Setting
`OAUTH_ISSUER` enables the OAuth path in parallel.

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

In Claude.ai → Settings → Integrations → Add custom integration:

- **Server URL:** `https://mcp-tcad.danteb.com`
- **Name:** `TCAD`

Claude will:
1. Call `/.well-known/oauth-protected-resource` → discovers the issuer.
2. Call `https://authelia.danteb.com/.well-known/openid-configuration` →
   discovers the registration + token endpoints.
3. POST to the registration endpoint (DCR) → receives a `client_id` /
   `client_secret` it stores internally.
4. Open a browser tab to Authelia's authorize URL → you log in (Authelia
   2FA per the policy).
5. Get redirected back to Claude with an auth code → exchanges it for
   tokens → makes the first MCP call with `Authorization: Bearer <JWT>`.

If any step fails, check Claude's error message and the Authelia logs
(`docker logs -f authelia`).

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

- [tcad-mcp README — Authentication section](https://github.com/dantebarbieri/tcad-mcp#authentication)
- [MCP authorization spec](https://modelcontextprotocol.io/specification/draft/basic/authorization)
- [RFC 9728 — OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728)
- [draft-ietf-oauth-resource-metadata](https://datatracker.ietf.org/doc/draft-ietf-oauth-resource-metadata/)
