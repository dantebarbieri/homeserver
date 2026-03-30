# MatrixRTC Setup

MatrixRTC enables end-to-end encrypted voice and video calls in Matrix clients like Element Web, Element Desktop, and Element X. It replaces the legacy 1:1 VoIP calling with a scalable, SFU-based architecture that supports group calls. Without it, clients will show `MISSING_MATRIX_RTC_FOCUS` when attempting calls.

For background on why this is needed, see [End-to-End Encrypted Voice and Video for Self-Hosted Community Users](https://element.io/blog/end-to-end-encrypted-voice-and-video-for-self-hosted-community-users/) from the Element blog.

**Components:**
- **[LiveKit Server](https://github.com/livekit/livekit)** — WebRTC Selective Forwarding Unit (SFU) that handles real-time media routing between call participants
- **[lk-jwt-service](https://github.com/element-hq/lk-jwt-service)** — MatrixRTC authorization service that bridges Matrix and LiveKit, validating Matrix OpenID tokens and issuing LiveKit JWTs

The architecture is described in the [Element Call self-hosting guide](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md): clients obtain an OpenID token from Synapse, exchange it for a LiveKit JWT via lk-jwt-service, then connect directly to the LiveKit SFU for media streaming.

## Generating Secrets

The MatrixRTC stack requires one secret stored in `.env`:

- `LIVEKIT_API_SECRET` — shared secret between LiveKit Server and lk-jwt-service for JWT authentication

Generate it using one of these methods:

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

Add the generated values to your `.env`:
```bash
# LiveKit (MatrixRTC)
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=<generated-secret>
```

> **Note:** `LIVEKIT_API_KEY` is an identifier, not a secret — `devkey` is fine for self-hosted setups. The `LIVEKIT_API_SECRET` must be a strong random string and must match the value in the [LiveKit config file](#livekit-configuration). See the [LiveKit authentication docs](https://docs.livekit.io/home/get-started/authentication/) for details.

## LiveKit Configuration

Create the LiveKit config file at `${DATA}/livekit/config.yaml`:

```yaml
# LiveKit SFU configuration
# Reference: https://github.com/livekit/livekit/blob/master/config-sample.yaml

# HTTP/WebSocket port for signalling (reverse proxied, not exposed publicly)
port: 7880

# WebRTC media transport
rtc:
  # ICE/TCP fallback port — must be forwarded on router
  tcp_port: 7881
  # UDP mux: route all UDP media through a small set of ports instead of a large range.
  # Best practice for Docker — avoids massive iptables overhead from publishing thousands of ports.
  # The LiveKit config reference recommends "a range of ports ≥ the number of CPU cores/threads"
  # for best performance. For a 32-thread CPU: 7882-7913 (32 ports).
  # https://github.com/livekit/livekit/blob/master/config-sample.yaml
  udp_port: 7882-7913
  # Use STUN to discover public IP automatically (recommended for dynamic IPs)
  use_external_ip: true
  # If STUN discovery fails, comment out use_external_ip and set your public IP explicitly:
  # node_ip: YOUR_PUBLIC_IP

# Disable automatic room creation so lk-jwt-service controls access
# Required by lk-jwt-service: https://github.com/element-hq/lk-jwt-service#%EF%B8%8F-configuration
room:
  auto_create: false

# Logging
logging:
  level: info

# LiveKit's built-in TURN is disabled — Coturn handles TURN/STUN separately
turn:
  enabled: false

# API key/secret pair — must match LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env
keys:
  devkey: "<LIVEKIT_API_SECRET from .env>"
```

> **NAT:** If STUN discovery doesn't work, replace `use_external_ip: true` with `node_ip: YOUR_PUBLIC_IP` (your server's actual public IP). Without a correct public IP, remote users won't be able to connect to calls. See the [LiveKit config reference](https://github.com/livekit/livekit/blob/master/config-sample.yaml) for all available options.
>
> **Keys:** The `keys` section maps API key names to their secrets. Replace `<LIVEKIT_API_SECRET from .env>` with the same secret value you set in `.env`. The key name (`devkey`) must match `LIVEKIT_API_KEY` in `.env`. There is no security benefit to changing `devkey` to something else — it is a public identifier (like a username), not a secret. All security comes from `LIVEKIT_API_SECRET`.

## Synapse Configuration

Add the following to `${DATA}/synapse/data/homeserver.yaml` to enable the MSCs required by MatrixRTC. These settings come directly from the [Element Call self-hosting prerequisites](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md#a-matrix-homeserver):

```yaml
# MatrixRTC prerequisites
# https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md#a-matrix-homeserver

experimental_features:
  # MSC3266: Room summary API — used for knocking over federation
  msc3266_enabled: true
  # MSC4222: Adding state_after to sync v2 — allows clients to correctly
  # track room state, required for reliable call participation
  msc4222_enabled: true

# MSC4140: Delayed events — required for proper call participation signalling.
# Without this, calls may appear "stuck" in Matrix rooms.
max_event_delay_duration: 24h

# Rate limits tuned for MatrixRTC call signalling
rc_message:
  # Must accommodate e2ee key sharing frequency (bursty)
  per_second: 0.5
  burst_count: 30

rc_delayed_event_mgmt:
  # Must accommodate heartbeat frequency (~every 5 seconds = 0.2/s)
  per_second: 1
  burst_count: 20
```

> **Important:** Synapse must have a listener with `federation` or `openid` resources enabled. This is the default configuration — if you haven't customized your `listeners` section, no changes are needed. The lk-jwt-service validates Matrix OpenID tokens by contacting your homeserver's federation API. See the [Synapse listener docs](https://element-hq.github.io/synapse/latest/usage/configuration/config_documentation.html#listeners) for details.
>
> **Restart required:** After editing `homeserver.yaml`, restart Synapse:
> ```bash
> docker restart synapse
> ```

## Reverse Proxy (Nginx Proxy Manager)

The [Element Call self-hosting guide](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md#matrix-site-endpoint-routing) recommends using a single hostname with path-based routing for the MatrixRTC backend:

| Path | Backend | Description |
|------|---------|-------------|
| `/livekit/sfu` | LiveKit Server (port 7880) | WebSocket signalling for media |
| `/livekit/jwt` | lk-jwt-service (port 8080) | JWT token exchange |

### DNS Record

If you have a wildcard record (`*.example.com`), the subdomain `livekit.example.com` will resolve automatically. Otherwise, create a record:
```
livekit.example.com    CNAME    example.com
```

### Create Proxy Host

In Nginx Proxy Manager, add a new proxy host:

- **Domain:** `livekit.example.com`
- **Scheme:** `http`
- **Forward Hostname/IP:** `livekit`
- **Forward Port:** `7880`
- **WebSocket Support:** ☑ Enabled
- **SSL:** Select your certificate, enable Force SSL

### Advanced Configuration

In the **Advanced** tab of the proxy host, add the following nginx directives to enable path-based routing. This follows the [official nginx configuration](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md#matrix-site-endpoint-routing) from the Element Call docs. These are standard nginx `location` blocks and are valid in NPM's Advanced tab, which injects raw nginx directives into the generated `server {}` block.

```nginx
# lk-jwt-service: MatrixRTC authorization / token exchange
# https://github.com/element-hq/lk-jwt-service#-transport-layer-security-tls-setup-using-a-reverse-proxy
location ^~ /livekit/jwt/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://lk-jwt-service:8080/;
}

# LiveKit SFU: WebSocket signalling connection
location ^~ /livekit/sfu/ {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_send_timeout 120;
    proxy_read_timeout 120;
    proxy_pass http://livekit:7880/;
}
```

> **Note:** The trailing `/` on each `proxy_pass` URL is required — it strips the location prefix from the forwarded request. Without it, lk-jwt-service would receive `/livekit/jwt/healthz` instead of `/healthz`. See the [nginx proxy_pass docs](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass) for how URI stripping works.
>
> **NPM behavior:** These `location ^~` blocks take priority over NPM's auto-generated `location /` block for any request path starting with `/livekit/jwt/` or `/livekit/sfu/`. All other paths fall through to NPM's default proxy (LiveKit on port 7880). Do not add Custom Locations in the NPM GUI for this proxy host — the Advanced tab handles everything.

## `.well-known` Update

The `.well-known/matrix/client` response must include `org.matrix.msc4143.rtc_foci` to announce the MatrixRTC backend to clients. This is defined in [MSC4143](https://github.com/matrix-org/matrix-spec-proposals/pull/4143) and documented in the [Element Call self-hosting guide](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md#matrixrtc-backend-announcement) and the [lk-jwt-service README](https://github.com/element-hq/lk-jwt-service#-do-not-forget-to-update-your-matrix-sites-well-knownmatrixclient).

Update the Advanced config on your **base domain** (`example.com`) proxy host in Nginx Proxy Manager. Replace the existing `/.well-known/matrix/client` block:

```nginx
location /.well-known/matrix/server {
    default_type application/json;
    add_header Access-Control-Allow-Origin *;
    return 200 '{"m.server": "matrix.example.com:443"}';
}

location /.well-known/matrix/client {
    default_type application/json;
    add_header Access-Control-Allow-Origin *;
    return 200 '{"m.homeserver": {"base_url": "https://matrix.example.com"}, "org.matrix.msc4143.rtc_foci": [{"type": "livekit", "livekit_service_url": "https://livekit.example.com/livekit/jwt"}]}';
}
```

For readability, the `/.well-known/matrix/client` response expands to:
```json
{
  "m.homeserver": {
    "base_url": "https://matrix.example.com"
  },
  "org.matrix.msc4143.rtc_foci": [
    {
      "type": "livekit",
      "livekit_service_url": "https://livekit.example.com/livekit/jwt"
    }
  ]
}
```

### Synapse `extra_well_known_client_content`

As belt-and-suspenders, also add the RTC foci to `homeserver.yaml`. This ensures the RTC focus is announced regardless of how clients discover the `.well-known` response. Add to `${DATA}/synapse/data/homeserver.yaml`:

```yaml
extra_well_known_client_content:
  org.matrix.msc4143.rtc_foci:
    - type: livekit
      livekit_service_url: "https://livekit.example.com/livekit/jwt"
```

> **Note:** This requires `public_baseurl` to be set in `homeserver.yaml` for Synapse to serve any `.well-known` response. See the [Synapse `extra_well_known_client_content` docs](https://element-hq.github.io/synapse/latest/usage/configuration/config_documentation.html#extra_well_known_client_content) for reference. If `public_baseurl` is not set, only the NPM-served `.well-known` above will be used — which is sufficient on its own.

## Port Forwarding

Forward the following ports on your router to your server's local IP:

| Port | Protocol | Service | Why |
|------|----------|---------|-----|
| `7881` | TCP | LiveKit RTC | ICE/TCP fallback for clients that can't use UDP (corporate firewalls) |
| `7882-7913` | UDP | LiveKit RTC | UDP-muxed WebRTC media transport (audio/video streams) |

> **UDP mux (Docker best practice):** Instead of publishing thousands of UDP ports through Docker's bridge network (which creates one iptables rule per port), LiveKit's `rtc.udp_port` option multiplexes all UDP media through a small fixed set of ports. This is the recommended approach for Docker deployments — it dramatically reduces iptables overhead and container startup time. The [LiveKit config reference](https://github.com/livekit/livekit/blob/master/config-sample.yaml) recommends **a port count ≥ the number of CPU threads** for best performance, so each thread can handle its own socket. Scale to your hardware — e.g., 8 threads → 8 ports (`7882-7889`), 32 threads → 32 ports (`7882-7913`), etc.
>
> **Why Coturn's large range is fine:** Unlike LiveKit, Coturn uses `network_mode: host` — it binds directly to the host network stack with zero Docker iptables overhead. Having 16,384 open relay ports (`49152-65535`) costs nothing extra compared to having 50. The TURN protocol ([RFC 5766](https://www.rfc-editor.org/rfc/rfc5766)) requires one port per relay allocation with no mux alternative, but `network_mode: host` makes this a non-issue. The overhead concern only applies to Docker bridge port publishing, which is exactly why LiveKit uses UDP mux instead.
>
> **Alternative — large port range:** If you prefer the traditional approach (e.g., for non-Docker deployments or `network_mode: host`), replace `udp_port` in the [LiveKit config](#livekit-configuration) with `port_range_start: 20000` / `port_range_end: 21000` and update `compose.matrix.yml` ports to `20000-21000:20000-21000/udp`. Each participant uses ~2 ports, so 1,001 ports supports ~500 concurrent participants. Keep this range below Coturn's relay range to avoid conflicts.

**Already forwarded** (no changes needed):
- `443/TCP` — LiveKit's WebSocket signalling (`wss://livekit.example.com/livekit/sfu`) flows through HTTPS, which is already forwarded to Nginx Proxy Manager
- `3478/TCP+UDP`, `5349/TCP+UDP` — Coturn TURN/STUN (if previously configured per [MATRIX.md](MATRIX.md))
- `49152-65535/UDP` — Coturn relay ports (if previously configured, does not overlap with LiveKit's range)

> **Note:** The 32 UDP-muxed ports (`7882-7913`) are not a per-participant limit — LiveKit multiplexes many streams per port. The port count affects parallelism, not capacity. See the [LiveKit deployment docs](https://docs.livekit.io/home/self-hosting/deployment/) and [ports reference](https://docs.livekit.io/transport/self-hosting/ports-firewall/) for resource guidance.

## Startup

1. **Create the config directory:**
   ```bash
   mkdir -p ${DATA}/livekit
   ```

2. **Create the LiveKit config** at `${DATA}/livekit/config.yaml` with the contents from [LiveKit Configuration](#livekit-configuration).

3. **Start the stack:**
   ```bash
   docker compose -f compose.matrix.yml up -d
   ```

## Verification

After starting the stack, verify each component in order:

1. **lk-jwt-service health check:**
   ```bash
   curl -s https://livekit.example.com/livekit/jwt/healthz
   ```
   Should return a `200 OK` response.

2. **`.well-known/matrix/client` includes RTC foci:**
   ```bash
   curl -s https://example.com/.well-known/matrix/client | python3 -m json.tool
   ```
   Confirm the response contains `org.matrix.msc4143.rtc_foci` with your `livekit_service_url`.

3. **LiveKit connectivity test:**
   Check container logs for successful startup:
   ```bash
   docker logs livekit 2>&1 | head -20
   ```
   Look for `starting LiveKit` and no error messages about ports or config.

4. **Test a call:** Open Element Web (or Element X) on two different devices/browsers, start a direct call between two users, and verify audio/video connects. For the most thorough test, have one user on a different network (e.g., mobile data) to confirm NAT traversal works.

> **Community test tool:** The [testmatrix](https://codeberg.org/spaetz/testmatrix/) tool can validate your MatrixRTC setup by testing JWT token exchange and LiveKit connectivity. Provide it with a Matrix username and access token to get a detailed diagnostics report.

## Troubleshooting

**`MISSING_MATRIX_RTC_FOCUS` still appears:**
- Verify `.well-known/matrix/client` returns the `org.matrix.msc4143.rtc_foci` field. Clients cache this response — try a hard refresh or clear app cache.
- Check CORS headers: the response must include `Access-Control-Allow-Origin: *`. Test with `curl -v`.
- Ensure no trailing slash issues in `livekit_service_url` — it should be `https://livekit.example.com/livekit/jwt` (no trailing slash).

**Calls connect but no audio/video (one-way or silent):**
- Confirm ports `7881/TCP` and `7882-7913/UDP` are forwarded on your router. Use an online port checker to verify.
- Check LiveKit's `node_ip` or `use_external_ip` setting. If your public IP is wrong, remote clients can't send media to the SFU.
- Review LiveKit logs: `docker logs livekit 2>&1 | grep -i "error\|warn"`.

**WebSocket connection fails (502 or timeout):**
- Verify WebSocket Support is enabled on the `livekit.example.com` proxy host in NPM.
- Check that the Advanced config `proxy_pass` URLs include the trailing `/`.
- Confirm the `livekit` and `lk-jwt-service` containers are on the `proxy` network: `docker network inspect proxy`.

**JWT token exchange fails (`/sfu/get` or `/get_token` returns errors):**
- Check lk-jwt-service logs: `docker logs lk-jwt-service`.
- Verify `LIVEKIT_KEY` and `LIVEKIT_SECRET` env vars match the `keys` section in `config.yaml`.
- Ensure Synapse's federation/openid listener is accessible. lk-jwt-service validates tokens by contacting your homeserver.

**Calls appear "stuck" (ringing indefinitely, participants don't see each other):**
- Confirm `max_event_delay_duration: 24h` is set in `homeserver.yaml` (enables MSC4140 delayed events).
- Verify `experimental_features` has both `msc3266_enabled: true` and `msc4222_enabled: true`.
- Restart Synapse after config changes: `docker restart synapse`.

**Room creation fails for federated users:**
- This is expected behavior. `LIVEKIT_FULL_ACCESS_HOMESERVERS` controls which homeservers can create LiveKit rooms. Federated users can join existing calls but cannot initiate them. See the [lk-jwt-service access control docs](https://github.com/element-hq/lk-jwt-service#-restrict-sfu-room-creation-to-selected-homeservers).

## Resources

- [Element Call Self-Hosting Guide](https://github.com/element-hq/element-call/blob/livekit/docs/self-hosting.md)
- [lk-jwt-service](https://github.com/element-hq/lk-jwt-service)
- [LiveKit Server](https://github.com/livekit/livekit)
- [LiveKit Self-Hosting / Deployment](https://docs.livekit.io/home/self-hosting/deployment/)
- [LiveKit Config Reference](https://github.com/livekit/livekit/blob/master/config-sample.yaml)
- [LiveKit Docker Image](https://hub.docker.com/r/livekit/livekit-server)
- [MSC4143: MatrixRTC Focus Discovery](https://github.com/matrix-org/matrix-spec-proposals/pull/4143)
- [MSC4195: MatrixRTC LiveKit Transport](https://github.com/matrix-org/matrix-spec-proposals/pull/4195)
- [Synapse Configuration Docs](https://element-hq.github.io/synapse/latest/usage/configuration/config_documentation.html)
- [Will Lewis: Deploy Element Call Backend with Docker Compose](https://willlewis.co.uk/blog/posts/deploy-element-call-backend-with-synapse-and-docker-compose/) (community guide)
- [testmatrix: MatrixRTC Sanity Tester](https://codeberg.org/spaetz/testmatrix/)
