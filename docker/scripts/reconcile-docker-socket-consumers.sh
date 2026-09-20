#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/srv/homeserver/docker}"
COMPOSE_LOCK_FILE="${COMPOSE_LOCK_FILE:-/run/lock/homeserver-compose.lock}"

fail() {
    printf 'Docker socket reconciliation failed: %s\n' "$*" >&2
    exit 1
}

[[ -r "$COMPOSE_DIR/docker-compose.yml" ]] ||
    fail "cannot read $COMPOSE_DIR/docker-compose.yml"

printf 'Waiting for Compose lock: %s\n' "$COMPOSE_LOCK_FILE"
exec 9>"$COMPOSE_LOCK_FILE" || fail "cannot open Compose lock"
flock --exclusive --timeout 600 9 || fail "could not acquire Compose lock within 600 seconds"
cd "$COMPOSE_DIR" || fail "cannot enter $COMPOSE_DIR"

for service in homepage alloy cadvisor vpn-netns-watcher; do
    # Query immediately before each recreate, excluding stopped and one-off containers.
    if ! running_ids=$(docker ps \
        --filter status=running \
        --filter label=com.docker.compose.project=compose \
        --filter "label=com.docker.compose.service=$service" \
        --filter label=com.docker.compose.oneoff=False \
        --format '{{.ID}}'); then
        fail "cannot enumerate running containers for $service"
    fi

    if [[ -z "$running_ids" ]]; then
        printf 'Skipping %s: no running compose service container\n' "$service"
        continue
    fi

    printf 'Refreshing Docker socket mount for %s\n' "$service"
    if ! docker compose \
        --project-name compose \
        --project-directory "$COMPOSE_DIR" \
        --file "$COMPOSE_DIR/docker-compose.yml" \
        up --no-deps --force-recreate --pull never --no-build -d "$service"; then
        fail "recreation failed for $service; remaining services were not attempted"
    fi
done

printf 'Docker socket consumer refresh completed\n'
