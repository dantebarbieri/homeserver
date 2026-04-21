#!/usr/bin/env bash
# install-mcp-config.sh — write /etc/openclaw/mcp-clients.json on the Pi.
# Run on a dev machine that has `ssh server` AND `ssh <pi-host>` configured.
# The Pi is firewalled away from the server by design, so this uses the
# dev machine as a trusted middleman — tokens stay in memory / short-lived
# tmpfiles, never stored long-term.
#
# Usage: ./install-mcp-config.sh [pi-ssh-host]    (default host: "pi")
set -euo pipefail

PI_HOST="${1:-pi}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SAMPLE="$HERE/mcp-clients.json.sample"

[ -f "$SAMPLE" ] || { echo "missing sample at $SAMPLE" >&2; exit 1; }

NAMES=(OPENZIM WIKIPEDIA WIKIDATA SEARXNG NOMINATIM PHOTON VALHALLA ELEV)
declare -A SERVER_KEY=(
  [OPENZIM]=openzim [WIKIPEDIA]=wikipedia [WIKIDATA]=wikidata-local
  [SEARXNG]=searxng [NOMINATIM]=nominatim [PHOTON]=photon
  [VALHALLA]=valhalla [ELEV]=elev
)

# Fetch all 8 tokens in one ssh round-trip.
echo "[1/3] fetching tokens from server…" >&2
TOKENS_TSV=$(ssh server 'for f in /srv/docker/data/mcp/secrets/MCP_TOKEN_*; do
  name=$(basename "$f" | sed "s/MCP_TOKEN_//")
  printf "%s\t%s\n" "$name" "$(cat "$f")"
done')
[ -n "$TOKENS_TSV" ] || { echo "no tokens returned from server" >&2; exit 1; }

# Build the filled config locally. Python because shell sed + secret values
# + JSON is a recipe for escaping bugs.
echo "[2/3] building config locally…" >&2
FILLED=$(
  TOKENS_TSV="$TOKENS_TSV" SAMPLE="$SAMPLE" python3 - <<'PY'
import json, os
tokens = dict(line.split('\t') for line in os.environ['TOKENS_TSV'].strip().splitlines())
with open(os.environ['SAMPLE']) as f:
    data = json.load(f)
mapping = {'openzim':'OPENZIM','wikipedia':'WIKIPEDIA','wikidata-local':'WIKIDATA',
           'searxng':'SEARXNG','nominatim':'NOMINATIM','photon':'PHOTON',
           'valhalla':'VALHALLA','elev':'ELEV'}
for key, name in mapping.items():
    if name not in tokens:
        raise SystemExit(f"token missing for {name}")
    data['servers'][key]['bearer'] = tokens[name]
print(json.dumps(data, indent=2))
PY
)

# Ship to Pi (stdin → /tmp on Pi → sudo install → chown openclaw → remove tmp).
# The Pi's sudo will prompt for password interactively if needed — that's
# why we use -t for a TTY.
echo "[3/3] installing on $PI_HOST (sudo will prompt if needed)…" >&2
echo "$FILLED" | ssh "$PI_HOST" 'cat > /tmp/mcp-clients.json.new && chmod 600 /tmp/mcp-clients.json.new'
ssh -t "$PI_HOST" 'sudo install -d -o root -g root -m 755 /etc/openclaw \
  && sudo install -m 600 -o openclaw -g openclaw /tmp/mcp-clients.json.new /etc/openclaw/mcp-clients.json \
  && rm -f /tmp/mcp-clients.json.new \
  && echo "installed /etc/openclaw/mcp-clients.json (openclaw:openclaw 0600)"'

echo "done. restart openclaw on the Pi to pick up the new config."
