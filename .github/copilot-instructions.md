# Copilot Instructions — homeserver monorepo

## Overview

This is a monorepo for a NixOS-based homeserver running 50+ Docker containers. Domain: `danteb.com`. All services are reverse-proxied via Nginx Proxy Manager with Authelia SSO.

### Repository Layout

- `docker/` — Docker Compose orchestration (17 category files, 50+ services)
- `nixos/` — NixOS system configuration (`configuration.nix`)
- `homepage/` — Homepage dashboard YAML config
- `mail-config/` — Portable email/contacts setup (aerc, khard, vdirsyncer)
- `recyclarr-configs/` — TRaSH Guides quality profiles for Sonarr/Radarr
- `production-configs/` — Gitignored dir for production config copies (only `README.md` tracked)

### Production Server

- Monorepo cloned at `/srv/homeserver`
- Docker data at `/srv/docker/data` (referenced as `${DATA}`)
- RAID storage at `/data` (referenced as `${RAID}`)
- Daily auto-update (04:00): pulls monorepo, then `cd docker && docker compose pull && build && up -d`

## Docker Compose (`docker/`)

### Architecture

`docker-compose.yml` is the main index file that uses the Compose `include:` directive to pull in category-specific compose files (`compose.*.yml`). Each category file is self-contained and can run independently with `docker compose -f compose.<category>.yml up -d`.

`compose.common.yml` is **never included** in `docker-compose.yml`. It provides base service templates (`common-service`, `hotio-service`, `linuxserver-service`, `gpu-service`) that other services reference via `extends:`. Think of it as an abstract base class file.

Hardware acceleration is split into two files (`hwaccel.transcoding.yml`, `hwaccel.ml.yml`) that provide device passthrough profiles consumed via `extends:`.

### Key environment variables

All services reference variables from `docker/.env` (not committed; see `docker/sample.env`):

- `${DATA}` — persistent service config/data (e.g., `/srv/docker/data`)
- `${RAID}` — bulk storage (media, torrents, photos)
- `${UID}` / `${GID}` / `${TZ}` — permissions and timezone
- `${TRAVEL_PLANNER_PATH}` / `${INTERVIEW_WORKSPACE_PATH}` — paths to external project repos

### Networking patterns

- **`proxy` network** — shared by all services with a web UI behind NPM. IPv6 enabled.
- **Internal networks** — purpose-specific (e.g., `authelia`, `immich`, `starr`, `komics`). Web-facing services join both `proxy` + internal; pure backends join only internal.
- **VPN namespace** — `vpn-netns` → `gluetun` → `qbittorrent` share one network via `network_mode: "container:vpn-netns"`.
- **Game servers** — direct host port mapping, no networks.
- Each compose file that references `proxy` declares it in its own `networks:` section for standalone compatibility.

### Commands (run from `docker/`)

```bash
docker compose up -d                              # Start all
docker compose -f compose.<category>.yml up -d    # Start one category
docker compose up -d <service>                    # Start one service
docker compose pull && docker compose up -d       # Update all
docker compose config                             # Validate merged config
./deploy-update.sh <service-name>                 # Zero-downtime deploy
```

### Adding a new service

1. Place it in the appropriate `compose.<category>.yml` (or create a new one and add to `include:` in `docker-compose.yml`).
2. Extend from `compose.common.yml` — choose `common-service`, `hotio-service`, `linuxserver-service`, or `gpu-service`.
3. Mount config to `${DATA}/<service-name>/config:/config`, bulk data under `${RAID}/shared/...`.
4. Web UI services → join `proxy` + a dedicated internal network. Pure backends → internal only.

### Secrets

Authelia secrets are Docker secrets (files under `${DATA}/authelia/secrets/`). Other services use environment variables from `.env`.

## NixOS (`nixos/`)

`configuration.nix` is the single-file declarative system config. Key services:
- Docker daemon (IPv6, CDI, live-restore)
- Auto-update timer (daily at 04:00, pulls this monorepo)
- RAID/drive monitoring (smartd, mdadm-ntfy, health checks)
- vdirsyncer (iCloud contacts every 15 minutes)
- SSH (key-only on port 28)

Rebuild: `sudo nixos-rebuild switch`

## Integration Points

- **NixOS → Docker**: enables daemon, daily auto-update pulls monorepo and restarts services
- **Homepage → Docker**: Docker socket + API widgets for live status
- **NPM → Authelia**: SSO middleware via nginx snippets
- **Recyclarr → Starr**: container in `compose.starr.yml`, syncs quality profiles via API
- **Mail → NixOS**: vdirsyncer runs as NixOS systemd timer
