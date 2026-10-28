#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    prepare|release) ;;
    *) echo "Usage: $0 prepare|release" >&2; exit 2 ;;
esac

running=$(docker ps -a --filter 'name=^/tdarr$' --format '{{.State}}')
if [[ -z "$running" || "$running" == exited || "$running" == created ]]; then
    exit 0
fi
if [[ "$running" != running ]]; then
    echo "ERROR: Tdarr is in state $running; refusing an unverified update." >&2
    exit 1
fi

if [[ "$1" == prepare ]]; then
    docker exec --user abc tdarr node /app/server/Tdarr/Custom/maintenance.cjs prepare
else
    # A recreated container needs time to register its internal node.
    for attempt in {1..30}; do
        if docker exec --user abc tdarr node /app/server/Tdarr/Custom/maintenance.cjs release; then
            exit 0
        fi
        sleep 2
    done
    echo "ERROR: Could not restore Tdarr's pause state; inspect Custom/update-lease.json." >&2
    exit 1
fi
