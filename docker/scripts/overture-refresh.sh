#!/usr/bin/env bash
# overture-refresh.sh — pull the latest Overture Maps places + divisions.
# Run monthly via the overture-refresh systemd timer (or manually).
# Public retention is 60 days; pinning a stale tag long-term will break.

set -euo pipefail

OPENCLAW_V3_BASE="${OPENCLAW_V3_BASE:-/data/openclaw-v3}"
NTFY_URL="${NTFY_URL:-https://ntfy.danteb.com}"
NTFY_TOPIC="${NTFY_TOPIC:-homeserver-alerts}"
THEMES=("${OVERTURE_THEMES:-places,divisions}")
STATE_FILE="${OPENCLAW_V3_BASE}/overture/.current-release"

# Ensure state dir exists even if openclaw-v3-bootstrap.sh hasn't been run.
mkdir -p "$(dirname "$STATE_FILE")"

notify() {
  local priority="$1" title="$2" body="$3"
  curl -fsS -H "Title: $title" -H "Priority: $priority" -H "Tags: world_map" \
    -d "$body" "${NTFY_URL}/${NTFY_TOPIC}" >/dev/null || true
}

command -v aws >/dev/null || { echo "aws cli required" >&2; exit 1; }

# Discover the latest release tag from the STAC catalog.
LATEST="$(curl -fsS https://stac.overturemaps.org/catalog.json \
  | python3 -c 'import json,sys; c=json.load(sys.stdin); ids=[l["href"].rsplit("/",2)[1] for l in c.get("links",[]) if l.get("rel")=="child"]; print(sorted(ids)[-1])')"

if [ -z "$LATEST" ]; then
  notify urgent "Overture refresh failed" "could not parse STAC catalog"
  exit 1
fi

CURRENT="$(cat "$STATE_FILE" 2>/dev/null || true)"
if [ "$CURRENT" = "$LATEST" ]; then
  echo "already at $LATEST — nothing to do."
  exit 0
fi

echo "syncing Overture release $LATEST (was: ${CURRENT:-none})"
IFS=',' read -ra THEME_LIST <<< "${THEMES[0]}"
for theme in "${THEME_LIST[@]}"; do
  dest="${OPENCLAW_V3_BASE}/overture/${theme}"
  mkdir -p "$dest"
  aws s3 sync \
    "s3://overturemaps-us-west-2/release/${LATEST}/theme=${theme}/" \
    "${dest}/" \
    --delete --no-sign-request --no-progress --only-show-errors
done

printf '%s' "$LATEST" > "$STATE_FILE"

notify default "Overture refreshed" "now at $LATEST (was ${CURRENT:-none})"
echo "overture-refresh complete."
