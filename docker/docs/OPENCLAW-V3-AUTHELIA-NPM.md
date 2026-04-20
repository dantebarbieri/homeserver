# OpenClaw v3 — Authelia + NPM runbook

After the OpenClaw v3 compose files land and bootstrap completes, this
runbook covers the on-server steps you can't commit to the repo (Authelia
config and NPM proxy hosts both live in the gitignored `${DATA}/`).

## 1. Authelia rules

`${DATA}/authelia/config/configuration.yml` — add to `access_control.rules:`,
in this order (specific rules first, deny last is the existing default):

```yaml
- domain:
  - 'ai-search.danteb.com'
  - 'cd.danteb.com'
  - 'kiwix.danteb.com'
  - 'nominatim.danteb.com'
  - 'photon.danteb.com'
  - 'valhalla.danteb.com'
  - 'elev.danteb.com'
  subject: 'group:admins'
  policy: one_factor

- domain: 'mcp.danteb.com'
  policy: bypass
```

`mcp.danteb.com` bypasses Authelia because each MCP container enforces
its own per-server static-bearer auth at the application layer — the
NPM access list provides defense-in-depth.

Restart Authelia: `dcr authelia`.

## 2. NPM proxy hosts

Each below corresponds to a Docker container on the `proxy` network. All
should have the LAN+WG access list attached.

| Host | Forward to | Notes |
|---|---|---|
| `ai-search.danteb.com` | `searxng-ai:8080` | LAN+WG access list |
| `cd.danteb.com`        | `changedetection-io:5000` | LAN+WG access list |
| `kiwix.danteb.com`     | `kiwix-serve:8080` | LAN+WG access list |
| `nominatim.danteb.com` | `nominatim:8080` | LAN+WG access list |
| `photon.danteb.com`    | `photon:2322`   | LAN+WG access list |
| `valhalla.danteb.com`  | `valhalla:8002` | LAN+WG access list |
| `elev.danteb.com`      | `opentopodata:5000` | LAN+WG access list |
| `mcp.danteb.com`       | varies — see below | LAN+WG access list, **Block Common Exploits OFF** |

### `mcp.danteb.com` proxy host (special)

Fan-routes 8 internal upstreams under a single TLS endpoint. In the Custom
Locations tab, create one location per server:

| Location | Forward Hostname | Forward Port |
|---|---|---|
| `/openzim/`     | `mcp-openzim`     | 8080 |
| `/wikipedia/`   | `mcp-wikipedia`   | 8080 |
| `/wikidata/`    | `mcp-wikidata`    | 8080 |
| `/searxng/`     | `mcp-searxng`     | 8080 |
| `/nominatim/`   | `mcp-nominatim`   | 8080 |
| `/photon/`      | `mcp-photon`      | 8080 |
| `/valhalla/`    | `mcp-valhalla`    | 8080 |
| `/elev/`        | `mcp-elev`        | 8080 |

In each location's Advanced tab AND the proxy host's main Advanced tab:

```nginx
include /snippets/mcp_streaming.conf;
```

The snippet itself is committed at `docker/nginx/snippets/mcp_streaming.conf`
and bind-mounted into NPM via the existing `${DATA}/nginxproxymanager/snippets:/snippets`
volume in `compose.core.yml`.

**Disable "Block Common Exploits"** on this proxy host — it false-positives
on JSON-RPC payloads.

## 3. LAN+WG access list

If not already created, set up an NPM Access List named `LAN+WG` with:

- **Satisfy Any**
- **Allow** entries:
  - `192.168.50.0/24` — LAN
  - `10.8.0.0/24` — WireGuard
  - `172.16.0.0/12` — Docker bridge networks
- **Deny all** (default)

Attach to every host in the table above.

## 4. Smoke tests after setup

From a LAN client:

```sh
# Authelia-protected (should return Authelia login page)
curl -isk https://ai-search.danteb.com/ | head -1

# MCP bearer-protected (should return 401 without bearer)
curl -isk https://mcp.danteb.com/wikipedia/ | head -1

# MCP with the right bearer (should return 200)
curl -isk -H "Authorization: Bearer $TOKEN" https://mcp.danteb.com/wikipedia/health
```

From WAN (cellular hotspot, off-VPN):

```sh
# Should return 403 (blocked by access list) for both
curl -isk https://ai-search.danteb.com/ | head -1
curl -isk https://mcp.danteb.com/wikipedia/health | head -1
```
