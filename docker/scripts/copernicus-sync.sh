#!/usr/bin/env bash
# copernicus-sync.sh — pull the Copernicus DEM rasters used by opentopodata
# and Valhalla. Long-running (~6–10 hours depending on bandwidth). Run
# manually inside tmux/screen.
#
# GLO-30 is the primary dataset (~130 GB). SRTM-30m is the void fallback
# (~73 GB). Both buckets are public; --no-sign-request avoids needing AWS
# credentials.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
# Source .env, skipping bash-readonly vars (UID, EUID, etc.) that would
# error under `set -e`. Docker compose parses .env directly so it sees them.
# Using eval instead of `. <(grep ...)` because process substitution
# doesn't propagate `set -a` through the FIFO.
set -a
eval "$(grep -vE '^(UID|EUID|PPID|SHELLOPTS|BASHOPTS|BASHPID)=' "$ENV_FILE")"
set +a
: "${OPENCLAW_V3_BASE:?set OPENCLAW_V3_BASE in .env}"

command -v aws >/dev/null || { echo "aws cli required: nix-shell -p awscli2" >&2; exit 1; }

GLO30_DIR="${OPENCLAW_V3_BASE}/elev/copernicus-glo30"
SRTM_DIR="${OPENCLAW_V3_BASE}/elev/srtm30m"

mkdir -p "$GLO30_DIR" "$SRTM_DIR"

echo "syncing Copernicus GLO-30 → $GLO30_DIR"
aws s3 sync s3://copernicus-dem-30m/ "$GLO30_DIR/" \
  --no-sign-request --no-progress --only-show-errors --delete

echo "syncing SRTM 30m fallback → $SRTM_DIR"
aws s3 sync s3://copernicus-dem-90m/ "$SRTM_DIR/" \
  --no-sign-request --no-progress --only-show-errors --delete

echo "copernicus sync complete."
