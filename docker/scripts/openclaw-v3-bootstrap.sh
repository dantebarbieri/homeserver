#!/usr/bin/env bash
# openclaw-v3-bootstrap.sh — create the directory tree for the v3 travel stack.
# Idempotent. Run once before `docker compose up -d` for the new services.
#
# Reads OPENCLAW_V3_BASE and DATA from docker/.env (defaults: /data/openclaw-v3
# and /srv/docker/data). Sets ownership to UID:GID from the same .env.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE — copy sample.env and fill it in" >&2; exit 1; }

# Source .env, skipping bash-readonly vars (UID, EUID, etc.) that would
# error under `set -e`. Docker compose parses .env directly so it sees them.
# Using eval instead of `. <(grep ...)` because process substitution
# doesn't propagate `set -a` through the FIFO.
set -a
eval "$(grep -vE '^(UID|EUID|PPID|SHELLOPTS|BASHOPTS|BASHPID)=' "$ENV_FILE")"
set +a

: "${OPENCLAW_V3_BASE:?set OPENCLAW_V3_BASE in .env}"
: "${DATA:?set DATA in .env}"
: "${UID:=1000}"
: "${GID:=1000}"

DIRS=(
  "${OPENCLAW_V3_BASE}"
  "${OPENCLAW_V3_BASE}/nominatim/pg"
  "${OPENCLAW_V3_BASE}/nominatim/flatnode"
  "${OPENCLAW_V3_BASE}/valhalla/tiles"
  "${OPENCLAW_V3_BASE}/valhalla/gtfs_feeds"
  "${OPENCLAW_V3_BASE}/photon"
  "${OPENCLAW_V3_BASE}/elev"
  "${OPENCLAW_V3_BASE}/elev/copernicus-glo30"
  "${OPENCLAW_V3_BASE}/elev/srtm30m"
  "${OPENCLAW_V3_BASE}/zim"
  "${OPENCLAW_V3_BASE}/overture"
  "${OPENCLAW_V3_BASE}/overture/places"
  "${OPENCLAW_V3_BASE}/overture/divisions"
  "${DATA}/mcp/secrets"
  "${DATA}/changedetection/datastore"
  "${DATA}/searxng-ai/state"
)

for d in "${DIRS[@]}"; do
  mkdir -p "$d"
  echo "ok: $d"
done

# Nominatim's image runs PG as the in-image 'nominatim' user (uid 999 in the
# 5.x image). Don't chown the PG dirs — let the entrypoint handle it.
chown -R "$UID:$GID" \
  "${OPENCLAW_V3_BASE}/zim" \
  "${OPENCLAW_V3_BASE}/overture" \
  "${OPENCLAW_V3_BASE}/elev" \
  "${OPENCLAW_V3_BASE}/photon" \
  "${OPENCLAW_V3_BASE}/valhalla" \
  "${DATA}/mcp" \
  "${DATA}/changedetection" \
  "${DATA}/searxng-ai"

chmod 700 "${DATA}/mcp/secrets"

echo "bootstrap complete."
