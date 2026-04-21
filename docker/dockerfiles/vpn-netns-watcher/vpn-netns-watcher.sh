#!/bin/sh
# Watches docker events for the VPN namespace container and force-recreates
# every sibling that shares its network namespace (network_mode:container:...)
# whenever the sandbox drifts. Fixes the zombie-netns problem where a pause
# image bump recreates vpn-netns but leaves gluetun/qbittorrent attached to
# the destroyed old sandbox.
set -eu

: "$NETNS_CONTAINER"
: "$NETNS_SERVICE"
: "$SIBLING_SERVICES"
: "$COMPOSE_DIR"
: "$DEBOUNCE"
: "$SETTLE"

cd "$COMPOSE_DIR"

log() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

sandbox_of_service() {
  id=$(docker compose ps -q "$1" 2>/dev/null | head -n1)
  [ -z "$id" ] && return 0
  docker inspect -f '{{.NetworkSettings.SandboxKey}}' "$id" 2>/dev/null || true
}

siblings_drifted() {
  netns=$(sandbox_of_service "$NETNS_SERVICE")
  if [ -z "$netns" ]; then
    log "  $NETNS_SERVICE has no sandbox yet; nothing to reconcile"
    return 1
  fi
  for svc in $SIBLING_SERVICES; do
    sb=$(sandbox_of_service "$svc")
    [ -z "$sb" ] && continue
    if [ "$sb" != "$netns" ]; then
      log "  drift: $svc sandbox=$sb expected=$netns"
      return 0
    fi
  done
  return 1
}

recreate_siblings() {
  # shellcheck disable=SC2086
  docker compose up -d --force-recreate --no-deps --no-build $SIBLING_SERVICES
}

log "vpn-netns-watcher up (netns=$NETNS_CONTAINER siblings='$SIBLING_SERVICES' compose=$COMPOSE_DIR)"

while true; do
  last_fire=0
  docker events \
    --filter type=container \
    --filter "container=$NETNS_CONTAINER" \
    --filter event=start \
    --format '{{.Time}} {{.Action}} {{.Actor.Attributes.name}}' \
  | while IFS= read -r ev; do
    log "event: $ev"
    now=$(date +%s)
    if [ $((now - last_fire)) -lt "$DEBOUNCE" ]; then
      log "  debounced"
      continue
    fi
    sleep "$SETTLE"
    if siblings_drifted; then
      log "  force-recreating: $SIBLING_SERVICES"
      if recreate_siblings; then
        last_fire=$now
        log "  recreate OK"
      else
        log "  recreate FAILED"
      fi
    else
      log "  no drift; no-op"
    fi
  done
  log "docker events stream ended; reconnecting in 5s"
  sleep 5
done
