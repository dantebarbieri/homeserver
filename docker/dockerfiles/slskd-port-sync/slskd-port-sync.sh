#!/bin/sh
# Keeps slskd's Soulseek listen port equal to gluetun-slskd's forwarded port.
# slskd's run-time option overlay is volatile (lost on restart), so the port is
# re-checked every CHECK_INTERVAL seconds and re-applied whenever it differs.
set -u

log() { echo "[$(date -Iseconds)] $*"; }

ntfy() {
  curl -s -H "Title: $1" -H "Priority: ${3:-high}" -H "Tags: ${4:-warning,computer}" \
    -d "$2" "${NTFY_URL}/${NTFY_TOPIC}" >/dev/null || log "WARNING: ntfy send failed"
}

api() {
  curl -sf -m 15 -H "X-API-Key: ${SLSKD_API_KEY}" -H "Content-Type: application/json" "$@"
}

# 60 polls * 5s = 5 minutes without a forwarded port before alerting.
PORT_MISSING_COUNT=0
MAX_PORT_MISSING="${MAX_PORT_MISSING:-60}"
PORT_ALERTED=0
FAIL_ALERTED=0

log "[slskd-port-sync] starting (host=${SLSKD_HOST}, port_file=${PORT_FILE})"

while :; do
  PORT="$(cat "$PORT_FILE" 2>/dev/null || true)"
  if [ -z "$PORT" ]; then
    PORT_MISSING_COUNT=$((PORT_MISSING_COUNT + 1))
    if [ "$PORT_MISSING_COUNT" -ge "$MAX_PORT_MISSING" ] && [ "$PORT_ALERTED" -eq 0 ]; then
      ntfy "slskd Port Sync: No Forwarded Port" \
        "gluetun-slskd has supplied no forwarded port for $((PORT_MISSING_COUNT * 5))s -- check gluetun-slskd logs."
      PORT_ALERTED=1
    fi
    sleep 5
    continue
  fi
  if [ "$PORT_ALERTED" -eq 1 ]; then
    ntfy "slskd Port Sync: Port Restored" "gluetun-slskd is forwarding port ${PORT} again" "low" "white_check_mark"
  fi
  PORT_MISSING_COUNT=0
  PORT_ALERTED=0

  CURRENT="$(api "http://${SLSKD_HOST}/api/v0/options" | grep -o '"listenPort":[0-9]*' | head -n1 | cut -d: -f2)"
  if [ -z "$CURRENT" ]; then
    log "slskd API not ready; retrying"
  elif [ "$CURRENT" = "$PORT" ]; then
    FAIL_ALERTED=0
  elif api -X PATCH -d "{\"soulseek\":{\"listenPort\":${PORT}}}" "http://${SLSKD_HOST}/api/v0/options" >/dev/null; then
    log "slskd listen port ${CURRENT} -> ${PORT}"
    FAIL_ALERTED=0
  else
    log "ERROR: failed to set slskd listen port to ${PORT}"
    if [ "$FAIL_ALERTED" -eq 0 ]; then
      ntfy "slskd Port Sync: Update Failed" "Could not set slskd listen port to ${PORT}"
      FAIL_ALERTED=1
    fi
  fi
  sleep "${CHECK_INTERVAL}"
done
