#!/bin/sh
set -eu

log() { echo "[$(date -Iseconds)] $*"; }

ntfy() {
  curl -s \
    -H "Title: $1" \
    -H "Priority: ${3:-high}" \
    -H "Tags: ${4:-warning,computer}" \
    -d "$2" \
    "${NTFY_URL}/${NTFY_TOPIC}" >/dev/null || log "WARNING: ntfy send failed"
}

log "[port-sync] starting (host=${QHOST}, port_file=${PORT_FILE})"

while :; do
  PORT="$(cat "$PORT_FILE" 2>/dev/null || true)"
  if [ -n "$PORT" ]; then
    log "Forwarded port is $PORT. Updating qBittorrent…"

    # Login
    if ! curl -sf -c /tmp/c \
      -d "username=${QUSER}&password=${QPASS}" \
      "http://${QHOST}/api/v2/auth/login" >/dev/null; then
      log "ERROR: qBittorrent login failed"
      ntfy "qBit Port Sync: Login Failed" \
        "Could not authenticate to qBittorrent at ${QHOST}"
      sleep "${CHECK_INTERVAL}"
      continue
    fi

    # Set preference
    if ! curl -sf -b /tmp/c \
      --data-urlencode "json={\"listen_port\":${PORT}}" \
      "http://${QHOST}/api/v2/app/setPreferences" >/dev/null; then
      log "ERROR: setPreferences failed"
      ntfy "qBit Port Sync: Update Failed" \
        "Could not set listen_port to ${PORT} on qBittorrent at ${QHOST}"
      sleep "${CHECK_INTERVAL}"
      continue
    fi

    # Confirm
    if curl -sf -b /tmp/c "http://${QHOST}/api/v2/app/preferences" \
      | grep -q "\"listen_port\":${PORT}"; then
      log "qBittorrent port successfully set to ${PORT}"
    else
      log "WARNING: listen_port not updated?"
      ntfy "qBit Port Sync: Verify Failed" \
        "Set listen_port to ${PORT} but verification failed on ${QHOST}"
    fi

    sleep "${CHECK_INTERVAL}"
  else
    log "Port file not found/empty; will retry."
    sleep 5
  fi
done
