#!/bin/sh
# grocy-ntfy: poll Grocy's stock/volatile endpoint and push low-stock alerts
# to an ntfy topic. Deduplicates: only re-alerts when the set of missing
# products actually changes (sorted name digest stored on disk so dedupe
# survives container restarts).

set -u

GROCY_URL="${GROCY_URL:-http://grocy}"
GROCY_NTFY_URL="${GROCY_NTFY_URL:-https://ntfy.danteb.com}"
GROCY_NTFY_TOPIC="${GROCY_NTFY_TOPIC:-grocy-alerts}"
GROCY_POLL_INTERVAL="${GROCY_POLL_INTERVAL:-3600}"
STATE_DIR="${STATE_DIR:-/state}"
STATE_FILE="${STATE_DIR}/last_digest"

# Validate interval is a positive integer
case "$GROCY_POLL_INTERVAL" in
  ''|*[!0-9]*)
    echo "[grocy-ntfy] ERROR: GROCY_POLL_INTERVAL must be a positive integer (got: '$GROCY_POLL_INTERVAL')" >&2
    exit 1
    ;;
esac

mkdir -p "$STATE_DIR" 2>/dev/null || true

log() { echo "[$(date -Iseconds)] $*"; }

last_digest=""
if [ -f "$STATE_FILE" ]; then
  last_digest="$(cat "$STATE_FILE" 2>/dev/null || echo "")"
fi

log "starting (grocy=$GROCY_URL, ntfy=$GROCY_NTFY_URL/$GROCY_NTFY_TOPIC, interval=${GROCY_POLL_INTERVAL}s)"

while :; do
  if [ -z "${GROCY_API_KEY:-}" ]; then
    log "GROCY_API_KEY is not set — generate one in Grocy (Settings → API keys), set it in .env, and recreate this container. Sleeping."
    sleep "$GROCY_POLL_INTERVAL"
    continue
  fi

  # -f makes curl fail on HTTP errors (401/500/etc), -sS silent but show errors
  resp="$(curl -fsS \
    -H "GROCY-API-KEY: $GROCY_API_KEY" \
    -H "Accept: application/json" \
    "${GROCY_URL}/api/stock/volatile" 2>&1)" || {
      log "WARNING: curl to ${GROCY_URL}/api/stock/volatile failed: $resp"
      sleep "$GROCY_POLL_INTERVAL"
      continue
    }

  # Validate JSON and extract missing items. Suppress jq errors so a malformed
  # response doesn't kill the loop.
  missing="$(echo "$resp" | jq -r '.missing_products[]? | "- \(.name) (need \(.amount_missing) more)"' 2>/dev/null || true)"

  if [ -z "$missing" ]; then
    # Nothing missing — reset digest so a fresh shortage triggers a new alert
    if [ -n "$last_digest" ]; then
      log "all items in stock; clearing dedupe state"
      last_digest=""
      rm -f "$STATE_FILE" 2>/dev/null || true
    fi
    sleep "$GROCY_POLL_INTERVAL"
    continue
  fi

  digest="$(echo "$missing" | sort -u | sha256sum | awk '{print $1}')"

  if [ "$digest" = "$last_digest" ]; then
    sleep "$GROCY_POLL_INTERVAL"
    continue
  fi

  count="$(echo "$missing" | wc -l | tr -d ' ')"
  body="$(printf 'Items running low:\n\n%s\n\nOrder soon to avoid running out.' "$missing")"

  if curl -fsS \
       -H "Title: ${count} item(s) running low" \
       -H "Priority: default" \
       -H "Tags: pill,warning,grocy" \
       -H "Click: https://grocy.danteb.com/shoppinglist" \
       -d "$body" \
       "${GROCY_NTFY_URL}/${GROCY_NTFY_TOPIC}" >/dev/null 2>&1; then
    last_digest="$digest"
    echo "$digest" > "$STATE_FILE" 2>/dev/null || true
    log "alerted on $count item(s): $(echo "$missing" | tr '\n' ';' | sed 's/;$//')"
  else
    log "WARNING: ntfy POST failed; will retry next interval"
  fi

  sleep "$GROCY_POLL_INTERVAL"
done
