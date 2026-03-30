# CLAUDE.md

This file provides guidance to Claude Code when working with the `docker/` directory.

## Key Files

- `docker-compose.yml` — Main index. Uses `include:` to pull in category files. Defines `proxy` network and Authelia secrets. **Do not change `name: compose`** — it would orphan 13 named Docker volumes.
- `compose.common.yml` — Base service templates consumed via `extends:` (never included directly).
- `compose.*.yml` — Self-contained category files. Each can run independently: `docker compose -f compose.<category>.yml up -d`.
- `hwaccel.transcoding.yml` / `hwaccel.ml.yml` — GPU passthrough profiles (nvenc, cuda, vaapi, etc.) consumed via `extends:`.
- `sample.env` — Template for `.env` (not committed). Documents all required variables.
- `deploy-update.sh` — Zero-downtime deploy: pulls monorepo, rebuilds one service, scales to 2, waits, scales back to 1.
- `setup-vpn-watcher.sh` / `vpn-watcher.sh` — Monitors gluetun health, auto-restarts qBittorrent on VPN failure.

## Service Templates (`compose.common.yml`)

All services should extend one of these:

| Template | What it adds |
|----------|-------------|
| `common-service` | `restart: unless-stopped`, JSON logging (10m/3 files) |
| `hotio-service` | + PUID/PGID/TZ for Hotio images |
| `linuxserver-service` | + PUID/PGID/TZ for LinuxServer.io images |
| `gpu-service` | + `devices: ["nvidia.com/gpu=all"]` |

## Custom Dockerfiles

- `Dockerfile.jellyfin` — Injects Finity theme CSS/JS into `index.html` via sed
- `Dockerfile.sveltekit` — Multi-stage Node 18 alpine build, parameterized via `ARG APP_NAME`

## Shell Scripts

All use `set -euo pipefail` (bash) or `set -eu` (POSIX sh).

- `deploy-update.sh <service>` — Pull, rebuild, zero-downtime restart
- `setup-vpn-watcher.sh` — One-time setup, copies vpn-watcher.sh to `${DATA}` path
- `vpn-watcher.sh` — Long-running Docker event monitor (POSIX sh, debounced restarts)

## Service-Specific Docs

- `MATRIX.md` — Synapse, Element, Coturn, PostgreSQL setup
- `MATRIX-RTC.md` — LiveKit voice/video call integration
- `NEXTCLOUD.md` — PostgreSQL, Redis, cron, reverse proxy config
- `TDARR.md` — HEVC compression, library setup, Sonarr/Radarr integration

## Conventions

- Volume mounts: config at `${DATA}/<service>/config:/config`, bulk data under `${RAID}/shared/...`
- External project paths use env vars (`${TRAVEL_PLANNER_PATH}`, `${INTERVIEW_WORKSPACE_PATH}`), not relative paths
- Secrets: Authelia uses Docker secrets (files in `${DATA}/authelia/secrets/`). Everything else uses `.env` variables.
- Use `docker compose` (not `docker-compose`)
