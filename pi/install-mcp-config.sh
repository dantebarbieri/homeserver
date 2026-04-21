#!/usr/bin/env bash
# install-mcp-config.sh — fetch MCP bearer tokens from the homeserver and
# write /etc/openclaw/mcp-clients.json. Run on the Pi as a sudoer who has
# `ssh server` set up. Idempotent — rerunning overwrites the existing file
# with the current server-side tokens.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SAMPLE="${1:-$HERE/mcp-clients.json.sample}"
DEST="/etc/openclaw/mcp-clients.json"
SECRETS_DIR_ON_SERVER="/srv/docker/data/mcp/secrets"

[ -f "$SAMPLE" ] || { echo "missing sample at $SAMPLE" >&2; exit 1; }

NAMES=(OPENZIM WIKIPEDIA WIKIDATA SEARXNG NOMINATIM PHOTON VALHALLA ELEV)

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
cp "$SAMPLE" "$TMP"

for name in "${NAMES[@]}"; do
  echo "  fetching MCP_TOKEN_$name …" >&2
  tok=$(ssh server "cat $SECRETS_DIR_ON_SERVER/MCP_TOKEN_$name")
  [ -n "$tok" ] || { echo "empty token for $name on server" >&2; exit 1; }
  # Escape & and | so sed doesn't interpret them.
  esc=${tok//&/\\&}
  esc=${esc//|/\\|}
  sed -i "s|PASTE_MCP_TOKEN_${name}_HERE|${esc}|" "$TMP"
done

if grep -q "PASTE_MCP_TOKEN_" "$TMP"; then
  echo "placeholders remain after substitution — refusing to install" >&2
  grep "PASTE_MCP_TOKEN_" "$TMP" >&2
  exit 1
fi
python3 -c "import json,sys; json.load(open('$TMP'))" || {
  echo "resulting file is not valid JSON — refusing to install" >&2
  exit 1
}

sudo install -d -o root -g root -m 755 /etc/openclaw
sudo install -m 600 -o openclaw -g openclaw "$TMP" "$DEST"
echo "installed $DEST (owner openclaw:openclaw, mode 600)"
echo "restart openclaw to pick up the new config."
