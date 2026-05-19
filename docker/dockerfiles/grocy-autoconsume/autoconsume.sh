#!/bin/sh
# grocy-autoconsume: wake once a day at $RUN_TIME (local TZ), find every
# product in the configured product group, and POST a `consume` for that
# product's quick_consume_amount. This is the "I take this every day no
# matter what" path — Grocy itself has no scheduled-consume feature.
#
# Pairs with grocy-ntfy: this decrements stock, grocy-ntfy alerts when
# the decrement crosses a product's min-stock threshold.
#
# Safety:
#   - Persists "last run date" to /state/last_run so a container restart
#     on the same day never double-consumes.
#   - Errors per-product are isolated; one failure doesn't abort the batch.
#   - On any consume failure, fires a high-priority ntfy push so you know
#     to manually check / adjust stock.

set -u

GROCY_URL="${GROCY_URL:-http://grocy}"
GROCY_AUTOCONSUME_GROUP="${GROCY_AUTOCONSUME_GROUP:-Auto-consume daily}"
GROCY_AUTOCONSUME_TIME="${GROCY_AUTOCONSUME_TIME:-08:00}"
GROCY_NTFY_URL="${GROCY_NTFY_URL:-https://ntfy.danteb.com}"
GROCY_NTFY_TOPIC="${GROCY_NTFY_TOPIC:-grocy-alerts}"
GROCY_AUTOCONSUME_DIGEST="${GROCY_AUTOCONSUME_DIGEST:-0}"
STATE_DIR="${STATE_DIR:-/state}"
STATE_FILE="${STATE_DIR}/last_run"

case "$GROCY_AUTOCONSUME_TIME" in
  [0-2][0-9]:[0-5][0-9]) : ;;
  *)
    echo "[grocy-autoconsume] ERROR: GROCY_AUTOCONSUME_TIME must be HH:MM (got: '$GROCY_AUTOCONSUME_TIME')" >&2
    exit 1
    ;;
esac

mkdir -p "$STATE_DIR" 2>/dev/null || true

log() { echo "[$(date -Iseconds)] $*"; }

ntfy_push() {
  # Usage: ntfy_push <priority> <title> <tags> <body>
  curl -sS -m 10 \
    -H "Title: $2" \
    -H "Priority: $1" \
    -H "Tags: $3" \
    -H "Click: https://grocy.danteb.com/stockoverview" \
    -d "$4" \
    "${GROCY_NTFY_URL}/${GROCY_NTFY_TOPIC}" >/dev/null 2>&1 \
    || log "WARNING: ntfy push failed"
}

run_consume_batch() {
  # 1. Find product group ID by name
  groups_json="$(curl -fsS -m 15 \
    -H "GROCY-API-KEY: $GROCY_API_KEY" \
    "${GROCY_URL}/api/objects/product_groups" 2>&1)" || {
      log "ERROR: failed to fetch product_groups: $groups_json"
      ntfy_push high "Grocy autoconsume failure" "warning,pill" \
        "Could not reach Grocy at ${GROCY_URL}. Daily medication consumption did NOT run."
      return 1
    }

  group_id="$(printf '%s' "$groups_json" \
    | jq -r --arg name "$GROCY_AUTOCONSUME_GROUP" \
        '.[] | select(.name == $name) | .id' 2>/dev/null || true)"

  if [ -z "$group_id" ] || [ "$group_id" = "null" ]; then
    log "Product group '$GROCY_AUTOCONSUME_GROUP' does not exist in Grocy — nothing to do"
    return 0
  fi

  # 2. Fetch all products in that group
  products_json="$(curl -fsS -m 15 \
    -H "GROCY-API-KEY: $GROCY_API_KEY" \
    "${GROCY_URL}/api/objects/products" 2>&1)" || {
      log "ERROR: failed to fetch products: $products_json"
      ntfy_push high "Grocy autoconsume failure" "warning,pill" \
        "Could not list products. Daily medication consumption did NOT run."
      return 1
    }

  # product_group_id may come back as number or string depending on Grocy
  # version — coerce both sides to string for compare.
  matches="$(printf '%s' "$products_json" \
    | jq -c --arg gid "$group_id" \
        '.[] | select((.product_group_id | tostring) == $gid)
              | {id, name, qca: .quick_consume_amount}' 2>/dev/null || true)"

  if [ -z "$matches" ]; then
    log "No products in group '$GROCY_AUTOCONSUME_GROUP' — nothing to do"
    return 0
  fi

  successes=""
  failures=""

  # Loop via here-doc so the variable assignments persist (a piped
  # `while read` runs in a subshell on POSIX sh and loses state).
  while IFS= read -r row; do
    [ -z "$row" ] && continue
    pid="$(printf '%s' "$row" | jq -r '.id')"
    pname="$(printf '%s' "$row" | jq -r '.name')"
    amount="$(printf '%s' "$row" | jq -r '.qca')"

    case "$amount" in
      ''|null|0|0.0|0.00) amount=1 ;;
    esac

    if ! resp="$(curl -fsS -m 15 -X POST \
        -H "GROCY-API-KEY: $GROCY_API_KEY" \
        -H "Content-Type: application/json" \
        --data-binary "{\"amount\": $amount, \"transaction_type\": \"consume\", \"spoiled\": false}" \
        "${GROCY_URL}/api/stock/products/${pid}/consume" 2>&1)"; then
      log "ERROR: consume failed for '$pname' (id=$pid, amt=$amount): $resp"
      failures="${failures}- ${pname} (need ${amount}, error: $(printf '%s' "$resp" | head -c 120))
"
      continue
    fi

    log "consumed ${amount} of '${pname}' (id=${pid})"
    successes="${successes}- ${pname}: ${amount}
"
  done <<EOF
$matches
EOF

  if [ -n "$failures" ]; then
    body="$(printf 'Some daily medications could NOT be auto-consumed at %s:\n\n%s\nCheck stock manually.' \
      "$(date '+%Y-%m-%d %H:%M %Z')" "$failures")"
    ntfy_push high "Grocy autoconsume errors" "warning,pill" "$body"
  fi

  if [ -n "$successes" ] && [ "$GROCY_AUTOCONSUME_DIGEST" = "1" ]; then
    body="$(printf 'Auto-consumed today:\n\n%s' "$successes")"
    ntfy_push low "Grocy daily consume" "pill" "$body"
  fi

  return 0
}

last_run="$(cat "$STATE_FILE" 2>/dev/null || echo "")"
log "starting (grocy=$GROCY_URL, group='$GROCY_AUTOCONSUME_GROUP', time=$GROCY_AUTOCONSUME_TIME $(date +%Z), last_run=${last_run:-never})"

while :; do
  if [ -z "${GROCY_API_KEY:-}" ]; then
    log "GROCY_API_KEY not set — sleeping 1h"
    sleep 3600
    continue
  fi

  today="$(date +%Y-%m-%d)"
  now_ts="$(date +%s)"
  today_run_ts="$(date -d "today $GROCY_AUTOCONSUME_TIME" +%s 2>/dev/null)" || {
    log "ERROR: failed to parse 'today $GROCY_AUTOCONSUME_TIME'"; sleep 3600; continue
  }
  last_run="$(cat "$STATE_FILE" 2>/dev/null || echo "")"

  # Run if: (we haven't run today) AND (now is at-or-past today's scheduled time)
  if [ "$last_run" != "$today" ] && [ "$now_ts" -ge "$today_run_ts" ]; then
    log "running consume batch for $today"
    if run_consume_batch; then
      echo "$today" > "$STATE_FILE" 2>/dev/null || true
      last_run="$today"
    else
      log "batch failed; will retry next loop iteration"
      sleep 600
      continue
    fi
  fi

  # Compute sleep until next scheduled run
  if [ "$last_run" = "$today" ] || [ "$now_ts" -ge "$today_run_ts" ]; then
    next_run_ts="$(date -d "tomorrow $GROCY_AUTOCONSUME_TIME" +%s 2>/dev/null)"
  else
    next_run_ts="$today_run_ts"
  fi

  now_ts="$(date +%s)"
  sleep_for="$((next_run_ts - now_ts))"
  [ "$sleep_for" -lt 60 ] && sleep_for=60
  log "sleeping ${sleep_for}s until $(date -d "@${next_run_ts}" '+%Y-%m-%d %H:%M %Z')"
  sleep "$sleep_for"
done
