#!/bin/sh
set -eu

# ---- Config via env (with sane defaults) ----
GLUETUN_NAME="${GLUETUN_NAME:-gluetun}"
QBIT_NAME="${QBIT_NAME:-qbittorrent-app}"
QBIT_SERVICE="${QBIT_SERVICE:-qbittorrent}"      # compose service name
COMPOSE_FILE="${COMPOSE_FILE:-/compose/docker-compose.yml}"  # path to compose file
DEBOUNCE="${DEBOUNCE:-15}"                 # seconds between forced restarts
LOG_FILE="${LOG_FILE:-}"                   # e.g. /logs/vpn-watcher.log (optional)
VERBOSE_HEALTHCHECK="${VERBOSE_HEALTHCHECK:-0}"  # 1 to print exec_* healthcheck lines

# ---- Logger: stdout + optional file, with human timestamps ----
log() {
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  line="[$ts] $*"
  echo "$line"
  if [ -n "$LOG_FILE" ]; then
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    printf '%s\n' "$line" >> "$LOG_FILE"
  fi
}

# ---- helpers ----
qbit_running() {
  docker inspect -f '{{.State.Running}}' "$QBIT_NAME" 2>/dev/null | grep -qi true
}

is_gluetun_healthy_event() {
  ev="$1"
  # must be our gluetun container
  echo "$ev" | grep -q "\"name\":\"$GLUETUN_NAME\"" || return 1
  # modern: "Action":"health_status" + "health-status":"healthy"
  if   echo "$ev" | grep -q '"Action":"health_status"'           &&
       echo "$ev" | grep -q '"health-status":"healthy"'
  then
    return 0
  fi
  # legacy: "Action":"health_status: healthy" (or status field)
  if   echo "$ev" | grep -q '"Action":"health_status: healthy"'
  then
    return 0
  fi
  if   echo "$ev" | grep -q '"status":"health_status: healthy"'
  then
    return 0
  fi
  return 1
}

is_important_action() {
  # Only print the events we care about for readability
  # (start|stop|die|kill|restart|health_status*)
  echo "$1" | grep -Eq '"Action":"(start|stop|die|kill|restart|health_status|health_status: healthy)"'
}

is_exec_healthcheck() {
  # Gluetun runs healthchecks as execs; hide unless VERBOSE_HEALTHCHECK=1
  echo "$1" | grep -q '"Action":"exec_'
}

# ---- main ----
log "[vpn-watcher] listening for docker events (containers: $GLUETUN_NAME, $QBIT_NAME)..."

last_restart=0
docker events \
  --filter type=container \
  --filter "container=$GLUETUN_NAME" \
  --filter "container=$QBIT_NAME" \
  --format '{{json .}}' |
while IFS= read -r ev; do
  [ -z "$ev" ] && continue

  # reduce noise
  if is_exec_healthcheck "$ev"; then
    [ "$VERBOSE_HEALTHCHECK" = "1" ] && log "[event] $ev"
  else
    is_important_action "$ev" && log "[event] $ev"
  fi

  # Act only on Gluetun "healthy" edge
  if is_gluetun_healthy_event "$ev"; then
    now=$(date +%s)
    action_taken="none"

    # debounce
    if [ $(( now - last_restart )) -lt "$DEBOUNCE" ]; then
      action_taken="debounced"
      q_state="$(docker inspect -f '{{.State.Status}}' "$QBIT_NAME" 2>/dev/null || echo unknown)"
      log "[summary] gluetun=healthy qbit_before=${q_state} action=${action_taken}"
      continue
    fi

    if qbit_running; then
      log "[vpn-watcher] $GLUETUN_NAME healthy → recreating $QBIT_NAME via docker compose"
      
      # Use docker compose to properly recreate the container
      # This ensures clean state and proper network attachment
      cd "$(dirname "$COMPOSE_FILE")" 2>/dev/null || cd /compose
      if docker compose down "$QBIT_SERVICE" >/dev/null 2>&1 && \
         docker compose up -d "$QBIT_SERVICE" >/dev/null 2>&1; then
        action_taken="compose_recreate"
        last_restart="$now"
        log "[vpn-watcher] Successfully recreated $QBIT_SERVICE"
      else
        action_taken="compose_failed"
        log "[ERROR] Failed to recreate $QBIT_SERVICE via docker compose"
      fi
    else
      action_taken="qbit_not_running"
    fi

    q_state="$(docker inspect -f '{{.State.Status}}' "$QBIT_NAME" 2>/dev/null || echo unknown)"
    log "[summary] gluetun=healthy qbit_before=${q_state} action=${action_taken}"
  fi
done