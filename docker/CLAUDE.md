# CLAUDE.md

This file provides guidance to Claude Code when working with the `docker/` directory.

## Key Files

- `docker-compose.yml` — Main index. Uses `include:` to pull in category files. Defines `proxy` network and Authelia secrets. **Do not change `name: compose`** — it would orphan 13 named Docker volumes.
- `compose.common.yml` — Base service templates consumed via `extends:` (never included directly).
- `compose.*.yml` — Self-contained category files. Each can run independently: `docker compose -f compose.<category>.yml up -d`.
- `hwaccel.transcoding.yml` / `hwaccel.ml.yml` — GPU passthrough profiles (nvenc, cuda, vaapi, etc.) consumed via `extends:`.
- `sample.env` — Template for `.env` (not committed). Documents all required variables.

## Service Templates (`compose.common.yml`)

All services should extend one of these:

| Template | What it adds |
|----------|-------------|
| `common-service` | `restart: unless-stopped`, JSON logging (10m/3 files) |
| `hotio-service` | + PUID/PGID/TZ for Hotio images |
| `linuxserver-service` | + PUID/PGID/TZ for LinuxServer.io images |
| `gpu-service` | + `devices: ["nvidia.com/gpu=all"]` |

## Custom Dockerfiles (`dockerfiles/`)

- `dockerfiles/Dockerfile.jellyfin` — Injects Finity theme CSS/JS into `index.html` via sed
- `dockerfiles/Dockerfile.sveltekit` — Multi-stage Node 18 alpine build, parameterized via `ARG APP_NAME`
- `dockerfiles/bmc-monitor/` — Alpine with ipmitool, curl, jq + `bmc-ip-monitor.sh` polling script
- `dockerfiles/pi-monitor/` — Alpine with nmap, curl, jq + `pi-ip-monitor.sh` ARP scan polling script
- `dockerfiles/port-sync/` — curlimages/curl + `port-sync.sh` qBittorrent VPN port sync script
- `dockerfiles/vpn-netns-watcher/` — docker:cli + compose plugin + `vpn-netns-watcher.sh`; watches `vpn-netns` start events and force-recreates gluetun/qbittorrent/qbit-port-sync/qbit-manage when their network sandbox drifts from vpn-netns (e.g., after a `pause` image bump recreates vpn-netns and orphans the siblings on the destroyed netns)

## Shell Scripts (`scripts/`)

All use `set -euo pipefail` (bash) or `set -eu` (POSIX sh).

- `scripts/deploy-update.sh <service>` — Pull, rebuild, zero-downtime restart
- `scripts/setup-vpn-watcher.sh` — One-time setup, copies vpn-watcher.sh to `${DATA}` path
- `scripts/vpn-watcher.sh` — Long-running Docker event monitor (POSIX sh, debounced restarts)

## Service-Specific Docs (`docs/`)

- `docs/MATRIX.md` — Synapse, Element, Coturn, PostgreSQL setup
- `docs/MATRIX-RTC.md` — LiveKit voice/video call integration
- `docs/NEXTCLOUD.md` — PostgreSQL, Redis, cron, reverse proxy config
- `docs/TDARR.md` — HEVC compression, library setup, Sonarr/Radarr integration

## Conventions

- Volume mounts: config at `${DATA}/<service>/config:/config`, bulk data under `${RAID}/shared/...`
- External project paths use env vars (`${TRAVEL_PLANNER_PATH}`), not relative paths
- Secrets: Authelia uses Docker secrets (files in `${DATA}/authelia/secrets/`). Everything else uses `.env` variables.
- Use `docker compose` (not `docker-compose`)
- **Environment variables** — always use YAML dictionary format (`KEY: value`), not list-of-strings format (`- KEY=value`).
- **`extends` + `build` requires explicit `image:`** — The templates in `compose.common.yml` use `image: alpine` as a placeholder. When a service has both `extends:` and `build:`, Docker Compose tags the built image with the inherited `image:` name. If multiple services extend the same template and build, they all get tagged `alpine` and the last build overwrites the others. **Always set an explicit `image:` name** (e.g., `image: skyjo-frontend`) on any service that uses both `extends:` and `build:`.

## IPv6

Docker's daemon has `ipv6 = true` with `fixed-cidr-v6 = "fd00::/80"` (ULA) and `ip6tables = true` (NAT masquerade). This means containers use internal ULA addresses but can reach the internet over IPv6 via NAT to the host's public GUA — identical to how Docker handles IPv4.

- The `proxy` network has `enable_ipv6: true` — services on it can accept inbound IPv6 (via port mapping) and make outbound IPv6 connections.
- The `ddns` network (in `compose.core.yml`) also has `enable_ipv6: true` — used by ddclient for IPv6 address detection.
- Compose's auto-created `compose_default` network does **not** have IPv6. Services that need IPv6 must be on an explicitly IPv6-enabled network.
- When adding a new service that needs IPv6 connectivity, either put it on an existing IPv6-enabled network or create a new one with `enable_ipv6: true`.
