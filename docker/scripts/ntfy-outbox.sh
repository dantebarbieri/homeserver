#!/bin/sh

NTFY_OUTBOX="${NTFY_OUTBOX:-/var/lib/ntfy-outbox}"

ntfy_outbox_flush() {
  local entry title message priority tags
  mkdir "$NTFY_OUTBOX/.lock" 2>/dev/null || return 0
  for entry in "$NTFY_OUTBOX"/*.alert; do
    [ -f "$entry" ] || continue
    if ! title=$(sed -n '1p' "$entry") || ! priority=$(sed -n '2p' "$entry") ||
       ! tags=$(sed -n '3p' "$entry") || ! message=$(tail -n +4 "$entry"); then
      log "WARNING: ntfy outbox entry could not be read"
      break
    fi
    if ntfy_curl --fail --silent --show-error --max-time 20 \
      -H "Title: $title" -H "Priority: $priority" -H "Tags: $tags" \
      --data-raw "$message" "${NTFY_URL}/${NTFY_TOPIC}" >/dev/null; then
      if ! rm -f "$entry"; then
        log "WARNING: delivered ntfy outbox entry could not be removed"
        break
      fi
    else
      log "WARNING: ntfy send failed; alert remains queued"
      break
    fi
  done
  rmdir "$NTFY_OUTBOX/.lock" || log "WARNING: ntfy outbox lock could not be released"
}

ntfy_outbox_queue() {
  local entry dest
  entry=$(umask 077; mktemp "$NTFY_OUTBOX/.new.XXXXXX") || return 1
  dest="$NTFY_OUTBOX/$(date -u +%Y%m%dT%H%M%S)-${entry##*.}.alert"
  if ! printf '%s\n%s\n%s\n%s' "$1" "${3:-default}" "${4:-}" "$2" > "$entry" ||
     ! sync -d "$entry" ||
     ! mv "$entry" "$dest"; then
    rm -f "$entry"
    return 1
  fi
  sync -d "$NTFY_OUTBOX" || return 1
  ntfy_outbox_flush
}

ntfy_outbox_start() {
  mkdir -p "$NTFY_OUTBOX" || return 1
  if [ -d "$NTFY_OUTBOX/.lock" ]; then
    rmdir "$NTFY_OUTBOX/.lock" || return 1
  fi
  (
    ntfy_outbox_flush
    while :; do
      sleep 15
      ntfy_outbox_flush
    done
  ) &
}
