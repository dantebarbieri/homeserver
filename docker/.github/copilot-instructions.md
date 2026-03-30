# Copilot Instructions — homeserver-docker

## Architecture

This is a modular Docker Compose homeserver. `docker-compose.yml` is the main index file that uses the Compose `include:` directive to pull in category-specific compose files (`compose.*.yml`). It is **not** a monolith — each category file is self-contained and can be run independently with `docker compose -f compose.<category>.yml up -d`.

`compose.common.yml` is special: it is **never included** in `docker-compose.yml`. It provides base service templates (`common-service`, `hotio-service`, `linuxserver-service`, `gpu-service`) that other services reference via `extends:`. Think of it as an abstract base class file.

Hardware acceleration is split into two files (`hwaccel.transcoding.yml`, `hwaccel.ml.yml`) that provide device passthrough profiles (nvenc, cuda, vaapi, etc.) consumed via `extends:` — same pattern as `compose.common.yml`.

### Key environment variables

All services reference variables from `.env` (not committed; see `sample.env` for the template):

- `${DATA}` — host path for persistent service config/data (e.g., `/srv/docker/data`)
- `${RAID}` — host path for bulk storage (media, torrents, photos)
- `${UID}` / `${GID}` / `${TZ}` — shared across all services for permission and timezone consistency

### Networking patterns

- The shared network for services behind **Nginx Proxy Manager (NPM)** is called `proxy` (IPv6 enabled, defined in `docker-compose.yml`). Only services with a web UI that NPM reverse-proxies should join this network.
- Backend/internal services that don't need proxying are isolated to purpose-specific internal networks shared only with the minimum set of services that need them:
  - `authelia` — authelia ↔ authelia_postgres, authelia_redis
  - `immich` — immich-server ↔ immich-machine-learning, immich-redis, immich-postgres
  - `starr` — radarr, sonarr, bazarr, prowlarr, seerr ↔ recyclarr, whisperasr
  - `flaresolverr` — flaresolverr ↔ prowlarr, suwayomi (cross-stack)
  - `anime` — jellyfin ↔ arm-server
  - `komics` — komga ↔ komf
  - `suwayomi` — suwayomi ↔ suwayomi_postgres
  - `searxng` — searxng ↔ searxng_redis
- Services that have a web UI join **both** `proxy` and their internal network (e.g., `authelia` is on `proxy` + `authelia`; `komga` is on `proxy` + `komics`). Pure backend services (databases, caches, ML workers) join **only** the internal network.
- Game servers use direct host port mapping (forwarded at the router) and specify **no networks** — they don't communicate with each other or need proxying.
- The VPN/torrent stack uses a shared network namespace: `vpn-netns` (pause container) → `gluetun` (VPN) → `qbittorrent` all share the same network via `network_mode: "container:vpn-netns"`. The `vpn-netns` container joins `proxy` with alias `qbittorrent` so NPM and starr apps can reach it.
- Services with no inter-service communication needs and no web UI (e.g., `ddclient`, `endlessh`) specify no networks and fall through to Docker's auto-created default bridge.
- Each compose file that references `proxy` declares it in its own `networks:` section for standalone compatibility (`docker compose -f compose.<category>.yml up -d`).

### Custom images

Two Dockerfiles build custom images locally:

- `Dockerfile.jellyfin` — patches Jellyfin's `index.html` to inject the Finity theme
- `Dockerfile.sveltekit` — generic multi-stage build for SvelteKit apps, parameterized via `ARG APP_NAME`

## Commands

```bash
# Start all services
docker compose up -d

# Start a single category
docker compose -f compose.gaming.yml up -d

# Start a single service
docker compose up -d radarr

# Pull all images and restart changed services
docker compose pull && docker compose up -d

# Validate the merged config
docker compose config

# Zero-downtime deploy for a git submodule service
./deploy-update.sh <submodule-name>

# Set up the VPN watcher (qBittorrent auto-restart on gluetun health)
./setup-vpn-watcher.sh
```

## Conventions

### Adding a new service

1. Place it in the appropriate `compose.<category>.yml` file, or create a new category file.
2. Extend from `compose.common.yml` — choose the right template:
   - `common-service` — baseline restart policy + log rotation
   - `hotio-service` — for Hotio images (adds PUID/PGID/TZ)
   - `linuxserver-service` — for LinuxServer.io images (adds PUID/PGID/TZ)
   - `gpu-service` — for NVIDIA GPU passthrough
3. Mount config to `${DATA}/<service-name>/config:/config` (or similar) and bulk data under `${RAID}/shared/...`.
4. If the new category file is standalone, add it to the `include:` list in `docker-compose.yml`.
5. If the service has a web UI that should be reverse-proxied, add it to the `proxy` network. If it also has backend dependencies (database, cache, etc.), create a dedicated internal network in the category file — the web-facing service joins both `proxy` + internal, backends join only internal.
6. If the service has no web UI and no inter-service communication needs (e.g., game servers), specify no `networks:` at all — it will use Docker's auto-created default bridge.
7. If the service needs to communicate with services in other compose files, use a shared internal network (e.g., `flaresolverr` network for cross-stack access) rather than putting non-proxied services on `proxy`.

### Secrets

Authelia secrets are managed via Docker secrets (files under `${DATA}/authelia/secrets/`), declared centrally in `docker-compose.yml` and consumed by the auth stack. Other services use environment variables from `.env`.
