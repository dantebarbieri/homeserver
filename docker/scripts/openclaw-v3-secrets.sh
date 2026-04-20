#!/usr/bin/env bash
# openclaw-v3-secrets.sh — generate the 8 MCP bearer tokens.
# Writes one 64-char hex token per file under ${DATA}/mcp/secrets/.
# Refuses to overwrite existing tokens (idempotent).
# Prints the tokens ONCE to stdout — record them in your password manager
# and copy them into the Pi-side OpenClaw mcp-clients.json.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

: "${DATA:?set DATA in .env}"
SECRETS_DIR="${DATA}/mcp/secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

NAMES=(OPENZIM WIKIPEDIA WIKIDATA SEARXNG NOMINATIM PHOTON VALHALLA ELEV)

printf '\n%s\n' "==== MCP BEARER TOKENS — copy these into the Pi ===="
for name in "${NAMES[@]}"; do
  f="${SECRETS_DIR}/MCP_TOKEN_${name}"
  if [ -e "$f" ]; then
    printf '%-12s already exists at %s — skipping\n' "$name" "$f" >&2
    continue
  fi
  token="$(openssl rand -hex 32)"
  umask 077
  printf '%s' "$token" > "$f"
  chmod 600 "$f"
  printf 'MCP_TOKEN_%-10s %s\n' "$name" "$token"
done

printf '\n%s\n' "Tokens are stored at $SECRETS_DIR. Restart MCP containers to pick them up."
