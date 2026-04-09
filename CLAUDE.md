# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Rules

- **Commit-and-push before suggesting a pull.** Whenever you tell the user to pull changes on the server (or try something that requires the latest code), you **must** commit and push first. Never say "pull and try" without having already pushed the commits.

## What This Is

A monorepo for homeserver infrastructure (domain: `danteb.com`). The server runs NixOS with 50+ Docker containers, an NVIDIA RTX 2070 SUPER for transcoding/ML, ~66TB RAID6 XFS storage, and ntfy-based alerting. All services are reverse-proxied via Nginx Proxy Manager, with Authelia SSO for services that lack built-in auth. Dual-stack IPv4/IPv6 with Spectrum ISP, ASUS GT-BE98 Pro router, and Cloudflare DNS (DNS-only, no proxy).

**DNS**: `*.danteb.com` is a wildcard CNAME pointing to `danteb.com`, which has A + AAAA records updated by ddclient. New subdomains need only an NPM proxy host — no Cloudflare changes required.

### Repository Layout

| Directory | Purpose |
|-----------|---------|
| `docker/` | Docker Compose orchestration — 17 category files, 50+ services |
| `nixos/` | NixOS system configuration — single `configuration.nix` |
| `homepage/` | Homepage dashboard YAML config |
| `mail-config/` | Portable email/contacts setup (aerc, khard, vdirsyncer) — also used on macOS |
| `recyclarr-configs/` | TRaSH Guides quality profiles for Sonarr/Radarr |
| `production-configs/` | Gitignored dir for production config copies (only `README.md` tracked) |

### Production Server Paths

- **Server IP**: `192.168.50.100` (IPv4), `2603:8080:1e00:1c97:9e6b:ff:fe45:2bc2` (IPv6 GUA)
- **Network**: `bond0` (active-backup) — `enp66s0f0` + `enp66s0f1`, MAC pinned to `enp66s0f1`
- **Monorepo clone**: `/srv/homeserver` (owned by root, pulled by systemd timer)
- **Docker data**: `/srv/docker/data` (persistent service configs)
- **Backward-compat symlink**: `/srv/docker/compose` → `/srv/homeserver/docker`
- **Bulk storage**: `/data` (RAID6 mount, referenced as `${RAID}`)
- **BMC (IPMI)**: `192.168.50.50` (ASRock Rack, dedicated IPMI port) — reverse-proxied at `https://ipmi.danteb.com` via NPM with Authelia SSO (admins-only, two-factor). BMC bonding must be **disabled** in BMC web UI (Settings → Network → Network Bond Configuration) or the host cannot reach the BMC. The BMC uses HTTPS (self-signed) with `proxy_ssl_verify off` in NPM.

### Router (ASUS GT-BE98 Pro)

**WARNING: Assume any router settings change triggers a reboot.** The ASUS GT-BE98 Pro reboots on many configuration changes (including DHCP DNS settings), causing a brief network outage for all LAN devices. Always warn the user before recommending router changes and suggest making them during a low-usage window. Never assert a router change is safe unless there is confirmed evidence it does not reboot.

| Setting Change | Reboots? |
|----------------|----------|
| LAN → DHCP Server → DNS Server | **Yes** |
| Firewall → IPv6 Firewall inbound rules | **Yes** |
| WAN → Virtual Server / Port Forwarding (IPv4) | No |

### External Projects (not in this repo)

Some Docker Compose services build from repos outside this monorepo. Their paths are configured via environment variables in `.env` (see `docker/sample.env`):
- `${TRAVEL_PLANNER_PATH}` — SvelteKit travel planning app (`compose.websites.yml`)

## Docker Compose (`docker/`)

### Architecture

`docker-compose.yml` is the main index — it uses the Compose `include:` directive to pull in category files (`compose.*.yml`). Each category file is self-contained and can run independently: `docker compose -f compose.<category>.yml up -d`.

`compose.common.yml` is **never included** — it provides base service templates (`common-service`, `hotio-service`, `linuxserver-service`, `gpu-service`) consumed via `extends:`. Similarly, `hwaccel.transcoding.yml` and `hwaccel.ml.yml` provide GPU passthrough profiles via `extends:`.

### Category Files

| File | Services |
|------|----------|
| `compose.ai.yml` | litellm, open-webui, whisperasr, postgres |
| `compose.core.yml` | nginxproxymanager, ddclient, endlessh, bmc-ip-monitor, pi-ip-monitor |
| `compose.auth.yml` | authelia, postgres, redis |
| `compose.dashboards.yml` | homepage, dashdot |
| `compose.downloads.yml` | vpn-netns, gluetun, qbittorrent, sabnzbd, flaresolverr, qbit-manage |
| `compose.gaming.yml` | minecraft, rlcraft, hytale, satisfactory |
| `compose.git.yml` | forgejo, postgres |
| `compose.immich.yml` | immich-server, immich-machine-learning, redis, postgres |
| `compose.matrix.yml` | synapse, element, coturn, livekit, lk-jwt-service, postgres |
| `compose.media.yml` | plex, jellyfin, anime-relations, komga, komf, suwayomi, calibre-web, postgres |
| `compose.nextcloud.yml` | nextcloud, nextcloud_cron, postgres, redis |
| `compose.searxng.yml` | searxng, redis (valkey) |
| `compose.starr.yml` | radarr, sonarr, bazarr, prowlarr, seerr, tdarr, recyclarr |
| `compose.utilities.yml` | vaultwarden, syncthing, ntfy, adguardhome, wg-easy, it-tools, code-server, convertx, stirling-image |
| `compose.websites.yml` | travel-planner |

### Networking Patterns

- **`proxy` network** — shared by all services with a web UI behind Nginx Proxy Manager. IPv6 enabled, defined in `docker-compose.yml`. Each category file redeclares it for standalone compatibility. Do not put non-web services on this network.
- **`ddns` network** — IPv6-enabled network for ddclient DDNS operations (defined in `compose.core.yml`).
- **Internal networks** — purpose-specific (e.g., `authelia`, `immich`, `starr`, `komics`). Web-facing services join both `proxy` + internal; pure backends (DBs, caches) join only internal.
- **VPN namespace** — `vpn-netns` (pause container) → `gluetun` → `qbittorrent` share one network via `network_mode: "container:vpn-netns"`. The pause container joins `proxy` with alias `qbittorrent`.
- **Game servers** — direct host port mapping, no networks defined.
- **No-network services** (endlessh) — fall through to Docker's default bridge. Note: ddclient uses the dedicated `ddns` network for IPv6.
- Cross-stack communication uses shared internal networks (e.g., `flaresolverr`) rather than putting non-proxied services on `proxy`.

### Subdomain Naming Convention

The default rule is: **use the container/service name as the subdomain** (e.g., `radarr.danteb.com`, `sonarr.danteb.com`, `authelia.danteb.com`). Then add NPM **redirection hosts** for common alternative names people might type (e.g., `torrent.danteb.com` → `qbittorrent.danteb.com`, `vpn.danteb.com` → `wireguard.danteb.com`).

**Exceptions** — some services use a shorter or more meaningful subdomain instead of the container name:

| Subdomain | Container | Why |
|-----------|-----------|-----|
| `calibre` | calibre-web | The library matters, not the frontend app |
| `cloud` | nextcloud | Canonical name in Nextcloud docs |
| `code` | code-server | Short canonical name |
| `git` | forgejo | The hosting concept matters, not the Gitea fork |
| `immich` | immich_server | Project name, not the `_server` suffix |
| `ipmi` | (BMC at 192.168.50.50) | Describes the protocol/interface |
| `matrix` | synapse | Matrix is the protocol, Synapse is the implementation |
| `tools` | it-tools | Short canonical name |
| `travel` | travel-planner | Shortened |
| `uptime` | uptime-kuma | The concept matters, not the tool |
| `wireguard` | wg-easy | WireGuard is the protocol, wg-easy is the UI |

The guiding principle: prefer the **concept, protocol, or canonical project name** over the specific container/implementation name when they differ meaningfully. If someone swaps the underlying app (e.g., Forgejo → Gitea → GitLab), the subdomain should still make sense.

### Environment Variables (from `.env`, not committed)

- `${DATA}` — persistent service config/data (e.g., `/srv/docker/data`)
- `${RAID}` — bulk storage (media, torrents, photos)
- `${UID}` / `${GID}` / `${TZ}` — permissions and timezone
- Authelia secrets use Docker secrets (files under `${DATA}/authelia/secrets/`)

### Custom Dockerfiles

- `dockerfiles/Dockerfile.jellyfin` — patches Jellyfin's `index.html` to inject the Finity theme
- `dockerfiles/Dockerfile.sveltekit` — generic multi-stage SvelteKit build, parameterized via `ARG APP_NAME`
- `dockerfiles/bmc-monitor/` — BMC IP monitor (ipmitool + NPM API updater)
- `dockerfiles/pi-monitor/` — Raspberry Pi IP monitor (nmap ARP scan + NPM API updater)
- `dockerfiles/port-sync/` — qBittorrent VPN port sync (gluetun forwarded port → qBit API)

### Adding a New Service

1. Place in appropriate `compose.<category>.yml` (or create a new one and add to `include:` in `docker-compose.yml`).
2. Extend from `compose.common.yml` — choose `common-service`, `hotio-service`, `linuxserver-service`, or `gpu-service`.
3. Mount config to `${DATA}/<service>/config:/config`, bulk data under `${RAID}/shared/...`.
4. Web UI services → join `proxy` + a dedicated internal network. Pure backends → internal only. No-comms services → no networks.
5. **Authelia SSO** — **Default stance: protect everything that doesn't protect itself.** Add Authelia (NPM forward auth) to any service with **no built-in auth** (e.g., Dashdot, OpenClaw, Prometheus) or **weak/untrustworthy auth** (e.g., BMC/IPMI). Services with solid built-in authentication (e.g., Grafana, Vaultwarden, Nextcloud, Open WebUI) handle their own security — do not double up. A few intentionally public services (e.g., IT-Tools) skip Authelia by design.
6. If the service exposes ports externally, add the port to **three places**: `networking.firewall` in `nixos/configuration.nix`, router IPv4 port forwarding, and router IPv6 firewall inbound rules.
7. **NPM proxy host** — create the proxy host in NPM. Use the container/service name as the subdomain by default; use a shorter/canonical name if it fits the exceptions in [Subdomain Naming Convention](#subdomain-naming-convention). Add **redirection hosts** (301) for common alternative names (e.g., `chat.danteb.com` → `openwebui.danteb.com`, `vpn.danteb.com` → `wireguard.danteb.com`). Enable **WebSockets** for services that stream (chat UIs, real-time dashboards). Enable **Block Common Exploits** for standard web apps but skip it for API proxies where it may interfere with large POST bodies.
8. Update `homepage/` — add the service to `services.yaml` (follow the pattern in `homepage/CLAUDE.md`), add widget API key env vars to `docker/sample.env` **and** the `environment:` block in `docker/compose.dashboards.yml` (Homepage only sees env vars explicitly passed through — `.env` alone is not enough), and document key retrieval in `homepage/WIDGET_API_KEYS.md`.

### Commands

**WARNING: Never use `docker compose -f compose.<category>.yml up -d` on the server.** Running a category file standalone creates a separate Docker network (e.g., `docker_proxy` instead of `compose_proxy`), which breaks inter-container networking and causes 502 errors in NPM. Always use the main `docker-compose.yml` entry point so all services share the correct networks.

```bash
docker compose up -d                              # Start all
docker compose up -d <service>                    # Start one service
docker compose pull && docker compose up -d       # Update all
docker compose config                             # Validate merged config
./scripts/deploy-update.sh <service-name>            # Zero-downtime service deploy
```

`docker compose -f compose.<category>.yml config` is safe for **validation only** (it doesn't create containers or networks).

### Shell Convenience Functions

Defined in `nixos/docker-functions.zsh` and available system-wide on the server via ZSH:

| Function | Usage | Purpose |
|----------|-------|---------|
| `dci <svc>` | `dci bazarr` | Show image info (repo, tag, digest, created) |
| `dce <svc> <cmd...>` | `dce postgres psql -U myuser mydb` | Exec command in running container |
| `dcs <svc>` | `dcs bazarr` | Interactive shell (tries bash, then sh) |
| `dcl [-s <time>] <svcs...>` | `dcl -s 30m bazarr whisperasr` | Follow logs with optional --since |
| `dcr [svcs...]` | `dcr bazarr whisperasr` | Restart/recreate services |
| `dcu` | `dcu` | Quick update: git pull, pull/build/up, light prune |
| `dcupdate` | `dcupdate` | Full update: down, git pull+push, pull/build/up, heavy prune |

## NixOS (`nixos/`)

`configuration.nix` is the single-file declarative system config for the homeserver (hostname: `homeserver`, IP: `192.168.50.100/24`).

Key system services managed by NixOS:
- **ZSH + zimfw** — default shell with plugin manager, Docker convenience functions in `nixos/docker-functions.zsh`, and nix helper functions — all sourced via `interactiveShellInit`
- **Docker daemon** — IPv6 (ip6tables NAT), CDI, live-restore enabled
- **Firewall** — explicitly opened ports for HTTP/HTTPS, Plex, Coturn, LiveKit, game servers
- **Auto-update timer** — daily at 04:00, pulls monorepo from GitHub (`/srv/homeserver`), then `cd docker && docker compose pull && build && up -d`
- **RAID/drive monitoring** — `smartd`, `mdadm-ntfy`, 6-hourly health checks, weekly Sunday parity scrub — all alert via ntfy
- **vdirsyncer** — syncs iCloud contacts every 15 minutes via CardDAV
- **SSH** — key-only on port 28

Rebuild: `sudo nixos-rebuild switch`

**Shell preference:** The server uses `zoxide` — always use `z` instead of `cd` when suggesting commands (e.g., `z /srv/homeserver`, not `cd /srv/homeserver`).

## Homepage Dashboard (`homepage/`)

YAML-based config for the [Homepage](https://gethomepage.dev/) dashboard. `services.yaml` defines all services with Docker container status monitoring, health checks via `siteMonitor`, and service-specific API widgets. `bookmarks.yaml` has external links and local management UIs (router, IPMI). See `WIDGET_API_KEYS.md` for obtaining API tokens.

When changing service URLs, IPs, or removing/renaming services, update the corresponding entries in `homepage/services.yaml` and `homepage/bookmarks.yaml` to keep the dashboard in sync.

## Mail Config (`mail-config/`)

Portable email/contacts setup: aerc (terminal email), khard (address book), vdirsyncer (CardDAV sync). Run `setup.sh` to install — it detects platform (macOS/Linux), symlinks configs, and bootstraps credential templates. Credentials use `pass` on Linux/WSL, Keychain on macOS.

## Recyclarr (`recyclarr-configs/`)

TRaSH Guides quality profiles synced to Sonarr/Radarr. See `recyclarr-configs/CLAUDE.md` for full details. Key points:
- 11 quality profiles per app (resolution tiers + anime + restrictive upper-bound)
- YAML anchors deduplicate custom format profile lists
- Language CFs intentionally excluded from anime profiles (Sonarr/Radarr misidentifies dual-audio)
- `secrets.yml` is gitignored — managed on server directly

```bash
# Run from docker directory on server
docker compose -f compose.starr.yml run --rm recyclarr sync
```

## Production Config Copies (`production-configs/`)

Copy production configs here for local debugging — all contents except `README.md` are gitignored. See `production-configs/README.md` for details on what to copy and where it lives on the server.

Common sources: ddclient (dynamic DNS), Nginx Proxy Manager (reverse proxy, TLS certs, Authelia SSO snippets). **These contain secrets — never commit them.**

## Integration Points

- **NixOS → Docker**: NixOS enables the Docker daemon and runs the daily auto-update timer that pulls this monorepo and restarts services
- **Homepage → Docker**: mounted Docker socket for container status; service API widgets for live stats
- **NPM → Authelia**: nginx snippets in NPM config provide SSO middleware (see `production-configs/` for reference copies)
- **NPM → Coturn**: Let's Encrypt certs from NPM are passed to Matrix's Coturn for RTC
- **Recyclarr → Starr**: runs as a container in `compose.starr.yml`, syncs quality profiles to Radarr/Sonarr via their APIs
- **Mail → NixOS**: vdirsyncer (in `mail-config/`) runs as a NixOS systemd timer on the server, syncing iCloud contacts every 15 minutes
- **ddclient → Cloudflare**: updates A (IPv4) and AAAA (IPv6) DNS records for `danteb.com` every 5 minutes. Requires an IPv6-enabled Docker network (`ddns`) so it can detect the host's public GUA via NAT.
- **NPM → BMC (IPMI)**: reverse-proxies `ipmi.danteb.com` to the ASRock Rack BMC at `https://192.168.50.50` with Authelia SSO (admins group, two-factor). Requires `proxy_ssl_verify off` (self-signed cert) and BMC bonding disabled (otherwise host→BMC traffic is blocked by NCSI sideband). The `bmc-ip-monitor` container auto-updates the proxy host if the BMC's DHCP IP changes.
- **Router → Server (IPv6)**: Unlike IPv4 port forwarding, IPv6 uses firewall allow-rules on the ASUS router (Firewall > IPv6 Firewall) specifying the server's GUA and permitted ports
