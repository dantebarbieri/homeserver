# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A monorepo for homeserver infrastructure (domain: `danteb.com`). The server runs NixOS with 50+ Docker containers, an NVIDIA RTX 2070 SUPER for transcoding/ML, ~66TB RAID6 XFS storage, and ntfy-based alerting. All services are reverse-proxied via Nginx Proxy Manager with Authelia SSO.

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

- **Monorepo clone**: `/srv/homeserver` (owned by root, pulled by systemd timer)
- **Docker data**: `/srv/docker/data` (persistent service configs)
- **Backward-compat symlink**: `/srv/docker/compose` → `/srv/homeserver/docker`
- **Bulk storage**: `/data` (RAID6 mount, referenced as `${RAID}`)

### External Projects (not in this repo)

Some Docker Compose services build from repos outside this monorepo. Their paths are configured via environment variables in `.env` (see `docker/sample.env`):
- `${TRAVEL_PLANNER_PATH}` — SvelteKit travel planning app (`compose.websites.yml`)
- `${INTERVIEW_WORKSPACE_PATH}` — YipitData interview portal (`compose.interview.yml`)

## Docker Compose (`docker/`)

### Architecture

`docker-compose.yml` is the main index — it uses the Compose `include:` directive to pull in category files (`compose.*.yml`). Each category file is self-contained and can run independently: `docker compose -f compose.<category>.yml up -d`.

`compose.common.yml` is **never included** — it provides base service templates (`common-service`, `hotio-service`, `linuxserver-service`, `gpu-service`) consumed via `extends:`. Similarly, `hwaccel.transcoding.yml` and `hwaccel.ml.yml` provide GPU passthrough profiles via `extends:`.

### Category Files

| File | Services |
|------|----------|
| `compose.core.yml` | nginxproxymanager, ddclient, endlessh |
| `compose.auth.yml` | authelia, postgres, redis |
| `compose.dashboards.yml` | homepage, dashdot |
| `compose.downloads.yml` | vpn-netns, gluetun, qbittorrent, sabnzbd, flaresolverr, qbit-manage |
| `compose.gaming.yml` | minecraft, rlcraft, hytale, satisfactory |
| `compose.immich.yml` | immich-server, immich-machine-learning, redis, postgres |
| `compose.matrix.yml` | synapse, element, coturn, livekit, lk-jwt-service, postgres |
| `compose.media.yml` | plex, jellyfin, arm-server, komga, komf, suwayomi, postgres |
| `compose.nextcloud.yml` | nextcloud, nextcloud_cron, postgres, redis |
| `compose.searxng.yml` | searxng, redis (valkey) |
| `compose.starr.yml` | radarr, sonarr, bazarr, prowlarr, whisperasr, seerr, tdarr, recyclarr |
| `compose.utilities.yml` | vaultwarden, syncthing, ntfy |
| `compose.websites.yml` | travel-planner |

### Networking Patterns

- **`proxy` network** — shared by all services with a web UI behind Nginx Proxy Manager. IPv6 enabled, defined in `docker-compose.yml`. Each category file redeclares it for standalone compatibility. Do not put non-web services on this network.
- **`ddns` network** — IPv6-enabled network for ddclient DDNS operations (defined in `compose.core.yml`).
- **Internal networks** — purpose-specific (e.g., `authelia`, `immich`, `starr`, `komics`). Web-facing services join both `proxy` + internal; pure backends (DBs, caches) join only internal.
- **VPN namespace** — `vpn-netns` (pause container) → `gluetun` → `qbittorrent` share one network via `network_mode: "container:vpn-netns"`. The pause container joins `proxy` with alias `qbittorrent`.
- **Game servers** — direct host port mapping, no networks defined.
- **No-network services** (endlessh) — fall through to Docker's default bridge. Note: ddclient uses the dedicated `ddns` network for IPv6.
- Cross-stack communication uses shared internal networks (e.g., `flaresolverr`) rather than putting non-proxied services on `proxy`.

### Environment Variables (from `.env`, not committed)

- `${DATA}` — persistent service config/data (e.g., `/srv/docker/data`)
- `${RAID}` — bulk storage (media, torrents, photos)
- `${UID}` / `${GID}` / `${TZ}` — permissions and timezone
- Authelia secrets use Docker secrets (files under `${DATA}/authelia/secrets/`)

### Custom Dockerfiles

- `Dockerfile.jellyfin` — patches Jellyfin's `index.html` to inject the Finity theme
- `Dockerfile.sveltekit` — generic multi-stage SvelteKit build, parameterized via `ARG APP_NAME`

### Adding a New Service

1. Place in appropriate `compose.<category>.yml` (or create a new one and add to `include:` in `docker-compose.yml`).
2. Extend from `compose.common.yml` — choose `common-service`, `hotio-service`, `linuxserver-service`, or `gpu-service`.
3. Mount config to `${DATA}/<service>/config:/config`, bulk data under `${RAID}/shared/...`.
4. Web UI services → join `proxy` + a dedicated internal network. Pure backends → internal only. No-comms services → no networks.
5. If the service exposes ports externally, add the port to **three places**: `networking.firewall` in `nixos/configuration.nix`, router IPv4 port forwarding, and router IPv6 firewall inbound rules.

### Commands

```bash
docker compose up -d                              # Start all
docker compose -f compose.<category>.yml up -d    # Start one category
docker compose up -d <service>                    # Start one service
docker compose pull && docker compose up -d       # Update all
docker compose config                             # Validate merged config
./deploy-update.sh <service-name>                  # Zero-downtime service deploy
```

## NixOS (`nixos/`)

`configuration.nix` is the single-file declarative system config for the homeserver (hostname: `homeserver`, IP: `192.168.1.100/24`).

Key system services managed by NixOS:
- **Docker daemon** — IPv6 (ip6tables NAT), CDI, live-restore enabled
- **Firewall** — explicitly opened ports for HTTP/HTTPS, Plex, Coturn, LiveKit, game servers
- **Auto-update timer** — daily at 04:00, pulls monorepo from GitHub (`/srv/homeserver`), then `cd docker && docker compose pull && build && up -d`
- **RAID/drive monitoring** — `smartd`, `mdadm-ntfy`, 6-hourly health checks, weekly Sunday parity scrub — all alert via ntfy
- **vdirsyncer** — syncs iCloud contacts every 15 minutes via CardDAV
- **SSH** — key-only on port 28

Rebuild: `sudo nixos-rebuild switch`

## Homepage Dashboard (`homepage/`)

YAML-based config for the [Homepage](https://gethomepage.dev/) dashboard. `services.yaml` defines all services with Docker container status monitoring, health checks via `siteMonitor`, and service-specific API widgets. See `WIDGET_API_KEYS.md` for obtaining API tokens.

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
- **Router → Server (IPv6)**: Unlike IPv4 port forwarding, IPv6 uses firewall allow-rules on the ASUS router (Firewall > IPv6 Firewall) specifying the server's GUA and permitted ports
