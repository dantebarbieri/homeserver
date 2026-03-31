# Matrix Setup

Matrix provides federated, self-hosted communication with text channels, voice, and video calls — a Discord alternative built on an open protocol.

**Components:**
- **Synapse** — Matrix homeserver (stores messages, handles federation)
- **Element** — Web client (Discord-like UI with spaces, threads, calls)
- **Coturn** — TURN/STUN server (enables voice/video through NAT)
- **PostgreSQL** — Database backend for Synapse

## Generating Secrets

The Matrix stack requires two secrets stored in `.env`:

- `SYNAPSE_DB_PASSWORD` — PostgreSQL password for the Synapse database
- `COTURN_AUTH_SECRET` — shared secret between Synapse and Coturn for TURN authentication

Both should be long, random strings (32+ characters). Generate them using one of these methods:

**openssl (recommended):**
```bash
openssl rand -base64 32
```

**pwgen:**
```bash
pwgen -s 48 1
```

**/dev/urandom:**
```bash
tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
```

**External password manager** (e.g. Bitwarden, 1Password): use the built-in password generator set to 48+ characters, alphanumeric.

Add the generated values to your `.env`:
```bash
SYNAPSE_DB_PASSWORD=<generated-password>
COTURN_AUTH_SECRET=<generated-secret>
```

## Initial Setup

> **Important:** The `server_name` is the domain that appears in Matrix user IDs (e.g., `@user:example.com`). This is typically your **base domain**, even if Synapse runs at a subdomain like `matrix.example.com`. Use `.well-known` delegation (see [Federation](#federation--well-known-delegation)) to point the base domain to your Synapse instance. The server_name **cannot be changed** after initial setup.

1. **Generate Synapse config:**
   ```bash
   docker run --rm -v ${DATA}/synapse/data:/data \
     -e SYNAPSE_SERVER_NAME=example.com \
     -e SYNAPSE_REPORT_STATS=no \
     matrixdotorg/synapse:latest generate
   ```

2. **Configure PostgreSQL** in `${DATA}/synapse/data/homeserver.yaml`:
   ```yaml
   database:
     name: psycopg2
     args:
       user: synapse
       password: "<SYNAPSE_DB_PASSWORD from .env>"
       database: synapse
       host: synapse_postgres
       cp_min: 5
       cp_max: 10
   ```

3. **Configure TURN** in `homeserver.yaml`:
   ```yaml
   turn_uris:
     - "turn:turn.example.com:3478?transport=udp"
     - "turn:turn.example.com:3478?transport=tcp"
     - "turns:turn.example.com:5349?transport=udp"
     - "turns:turn.example.com:5349?transport=tcp"
   turn_shared_secret: "<COTURN_AUTH_SECRET from .env>"
   turn_user_lifetime: 86400000
   turn_allow_guests: false
   ```

4. **Create Element config** at `${DATA}/element/config.json`:
   ```json
   {
     "default_server_config": {
       "m.homeserver": {
         "base_url": "https://matrix.example.com",
         "server_name": "example.com"
       }
     },
     "disable_custom_urls": true,
     "disable_guests": true,
     "default_theme": "dark"
   }
   ```

5. **Create Coturn config** at `${DATA}/coturn/turnserver.conf`:
   ```
   listening-port=3478
   tls-listening-port=5349
   fingerprint
   use-auth-secret
   static-auth-secret=<COTURN_AUTH_SECRET from .env>
   realm=example.com
   total-quota=100
   bps-capacity=0
   stale-nonce
   no-multicast-peers
   no-cli
   # NAT traversal: replace with your server's public IP
   external-ip=YOUR_PUBLIC_IP
   # Relay port range — open these in your firewall/router
   min-port=49152
   max-port=65535
   ```

   > **NAT:** Replace `YOUR_PUBLIC_IP` with your server's actual public IP (e.g., `203.0.113.50`). Without this, voice/video calls will fail for remote users.
   >
   > **TLS (optional):** For TURNS on port 5349, add `cert=` and `pkey=` lines pointing to your TLS certificate and private key. Without TLS certs, remove the `turns:` URIs from `homeserver.yaml` and the `tls-listening-port` line above.

6. **Start the stack:**
   ```bash
   docker compose -f compose.matrix.yml up -d
   ```

7. **Create your first user:**
   ```bash
   docker exec -it synapse register_new_matrix_user \
     -u admin -p <password> -a \
     -c /data/homeserver.yaml http://localhost:8008
   ```

## Reverse Proxy (Nginx Proxy Manager)

- **Synapse**: Proxy `matrix.example.com` → `synapse:8008` — enable WebSocket support
- **Element**: Proxy `element.example.com` → `element:80`

### Federation & .well-known Delegation

If your `server_name` (e.g., `example.com`) differs from where Synapse runs (e.g., `matrix.example.com`), configure `.well-known` delegation so other Matrix servers can discover yours.

Serve these JSON responses from your **base domain** (`https://example.com`):

**`/.well-known/matrix/server`:**
```json
{
  "m.server": "matrix.example.com:443"
}
```

**`/.well-known/matrix/client`:**
```json
{
  "m.homeserver": {
    "base_url": "https://matrix.example.com"
  }
}
```

In Nginx Proxy Manager, create a proxy host for `example.com` that serves these paths (or use Custom Locations returning the JSON directly with a 200 response).

> **Verify federation:** Use the [Matrix Federation Tester](https://federationtester.matrix.org/) to confirm your server is reachable.

## Registration

By default, Synapse disables public registration. To allow invite-only sign-ups, add to `homeserver.yaml`:

```yaml
enable_registration: true
registration_requires_token: true
```

Then generate a registration token via the [Admin API](https://element-hq.github.io/synapse/latest/usage/administration/admin_api/registration_tokens.html):
```bash
docker exec synapse curl -s -X POST \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"uses_allowed": 50}' \
  http://localhost:8008/_synapse/admin/v1/registration_tokens/new
```

Share the returned token with invitees — they enter it during account creation in Element.

> **Admin access token:** Log into Element as the admin user → **Settings** → **Help & About** → **Advanced** → copy the Access Token. See the [Synapse Admin API docs](https://element-hq.github.io/synapse/latest/usage/administration/admin_api/) for more details.

## Resources

- [Matrix Protocol](https://matrix.org/)
- [Synapse Admin Guide](https://element-hq.github.io/synapse/latest/)
- [Element Web](https://element.io/)
- [Coturn](https://github.com/coturn/coturn)
- [Matrix Federation Tester](https://federationtester.matrix.org/)
