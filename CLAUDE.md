# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A multi-component homeserver infrastructure managed across several independent subdirectories. The server runs NixOS with 50+ Docker containers, an NVIDIA RTX 2070 SUPER for transcoding/ML, software RAID with LVM, and ntfy-based alerting.

**Git-tracked repos:** `docker/`, `nixos/`, `homepage/`, `mail-config/`, `recyclarr-configs/`
**Production config copies (read-only reference):** `ddclient/`, `nginxproxymanager/` — these are configs copied directly from the production server. They are useful for debugging proxy routing and dynamic DNS issues, but should be treated as read-only. Do not modify them, do not track them in git, and take care not to leak any secrets they contain.

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

- **`proxy` network** — shared by all services with a web UI behind Nginx Proxy Manager. IPv6 enabled, defined in `docker-compose.yml`. Each category file redeclares it for standalone compatibility.
- **Internal networks** — purpose-specific (e.g., `authelia`, `immich`, `starr`, `komics`). Web-facing services join both `proxy` + internal; pure backends (DBs, caches) join only internal.
- **VPN namespace** — `vpn-netns` (pause container) → `gluetun` → `qbittorrent` share one network via `network_mode: "container:vpn-netns"`. The pause container joins `proxy` with alias `qbittorrent`.
- **Game servers** — direct host port mapping, no networks defined.
- **No-network services** (ddclient, endlessh) — fall through to Docker's default bridge.
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

### Commands

```bash
docker compose up -d                              # Start all
docker compose -f compose.<category>.yml up -d    # Start one category
docker compose up -d <service>                    # Start one service
docker compose pull && docker compose up -d       # Update all
docker compose config                             # Validate merged config
./deploy-update.sh <submodule-name>               # Zero-downtime submodule deploy
```

## NixOS (`nixos/`)

`configuration.nix` is the single-file declarative system config for the homeserver (hostname: `homeserver`, IP: `192.168.1.100/24`).

Key system services managed by NixOS:
- **Docker daemon** — IPv6, CDI, live-restore enabled
- **Auto-update timer** — daily at 04:00, pulls from GitHub (`/srv/docker/compose`), runs `docker compose pull && build && up -d`
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

## Production Config Copies (`ddclient/`, `nginxproxymanager/`)

These directories contain configuration files copied directly from the production server for reference:

- **`ddclient/config/ddclient.conf`** — Dynamic DNS configuration (provider settings, update intervals, domain mappings)
- **`nginxproxymanager/`** — Reverse proxy config including the SQLite database, generated nginx configs, Let's Encrypt certificates, and Authelia SSO integration snippets (`snippets/authelia-authrequest.conf`, `snippets/authelia-location.conf`, `snippets/proxy.conf`)

These are read-only references for debugging. **Do not modify, do not commit to git, and do not expose secrets from these files.**

## Integration Points

- **NixOS → Docker**: NixOS enables the Docker daemon and runs the daily auto-update timer that pulls the `docker/` repo and restarts services
- **Homepage → Docker**: mounted Docker socket for container status; service API widgets for live stats
- **NPM → Authelia**: nginx snippets in `nginxproxymanager/snippets/` provide SSO middleware
- **NPM → Coturn**: Let's Encrypt certs from `nginxproxymanager/letsencrypt/` are passed to Matrix's Coturn for RTC
- **Recyclarr → Starr**: runs as a container in `compose.starr.yml`, syncs quality profiles to Radarr/Sonarr via their APIs
