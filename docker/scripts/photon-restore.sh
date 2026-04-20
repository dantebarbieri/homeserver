#!/usr/bin/env bash
# photon-restore.sh — download and extract the Photon prebuilt planet index.
# Rebuilding from scratch takes 12–24 hours; restoring the dump takes ~1 hour.
# Run manually after the photon container is created but before it has built
# its own index.

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
: "${PHOTON_DOWNLOAD_URL:?set PHOTON_DOWNLOAD_URL in .env}"

PHOTON_DIR="${OPENCLAW_V3_BASE}/photon"
mkdir -p "$PHOTON_DIR"

if [ -d "${PHOTON_DIR}/photon_data/node_mapping" ]; then
  echo "photon index already populated at $PHOTON_DIR/photon_data — refusing to overwrite." >&2
  echo "to force a fresh restore: rm -rf $PHOTON_DIR/photon_data" >&2
  exit 1
fi

echo "stopping photon container so we can populate the bind mount"
( cd "$ROOT_DIR" && docker compose stop photon ) || true

echo "downloading Photon dump from $PHOTON_DOWNLOAD_URL"
cd "$PHOTON_DIR"
curl -fL --retry 5 --retry-delay 30 -o photon-db.tar.bz2 "$PHOTON_DOWNLOAD_URL"

echo "extracting (this takes a while)"
pbzip2 -dc photon-db.tar.bz2 2>/dev/null | tar -xf - || tar -xjf photon-db.tar.bz2

rm photon-db.tar.bz2

echo "starting photon"
( cd "$ROOT_DIR" && docker compose up -d photon )
echo "photon-restore complete."
