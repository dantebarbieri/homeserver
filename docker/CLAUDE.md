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
- `dockerfiles/port-sync/` — curlimages/curl + `port-sync.sh` qBittorrent VPN port sync script

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
- External project paths use env vars (`${TRAVEL_PLANNER_PATH}`, `${INTERVIEW_WORKSPACE_PATH}`), not relative paths
- Secrets: Authelia uses Docker secrets (files in `${DATA}/authelia/secrets/`). Everything else uses `.env` variables.
- Use `docker compose` (not `docker-compose`)

## IPv6

Docker's daemon has `ipv6 = true` with `fixed-cidr-v6 = "fd00::/80"` (ULA) and `ip6tables = true` (NAT masquerade). This means containers use internal ULA addresses but can reach the internet over IPv6 via NAT to the host's public GUA — identical to how Docker handles IPv4.

- The `proxy` network has `enable_ipv6: true` — services on it can accept inbound IPv6 (via port mapping) and make outbound IPv6 connections.
- The `ddns` network (in `compose.core.yml`) also has `enable_ipv6: true` — used by ddclient for IPv6 address detection.
- Compose's auto-created `compose_default` network does **not** have IPv6. Services that need IPv6 must be on an explicitly IPv6-enabled network.
- When adding a new service that needs IPv6 connectivity, either put it on an existing IPv6-enabled network or create a new one with `enable_ipv6: true`.
