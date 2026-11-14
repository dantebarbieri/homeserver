#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: install-tdarr-offload.sh [--adopt | --rollback | --hold | --release] [--pools N] [--mac-node NAME] [--apply]

Copies the Tdarr offload modules into the container, then runs install-offload-flow.cjs with the same
arguments. Without --apply it only prints the plan; the module copy is idempotent and always happens.
  (no mode)   install the offload flow and a disabled canary library (TV libraries untouched)
  --adopt     move the TV libraries onto the offload flow (Linux CPU workers must be idle and at 0)
  --rollback  move the TV libraries back to the Linux-only flow
  --hold      uncheck every schedule slot of the TV libraries, so nothing new starts (running jobs finish)
  --release   check every schedule slot again, once the nodes match the flow the TV libraries use
  --pools N   x265 thread pools per encode, 1-64 (only with no mode or --adopt)
EOF
    exit 2
}

args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
        --adopt | --rollback | --hold | --release | --apply) ;;
        --pools | --mac-node) i=$((i + 1)) ;;
        *) usage ;;
    esac
done

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
container="${TDARR_CONTAINER:-tdarr}"
destination=/app/server/Tdarr/Custom

if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]]; then
    echo "ERROR: Tdarr container is not running." >&2
    exit 1
fi

docker exec "$container" mkdir -p "$destination/backups"
backup="$destination/backups/modules-$(date +%s)"
docker exec "$container" mkdir "$backup"
for file in dv5-sidecar.cjs install-flow.cjs hevc-safe-v1.cjs hevc-offload-v1.cjs install-safe-flows.cjs \
    install-offload-flow.cjs configure-offload-nodes.cjs maintenance.cjs reconcile-sidecars.cjs recover-policy-errors.cjs; do
    if docker exec "$container" test -f "$destination/$file"; then
        docker exec "$container" cp -p "$destination/$file" "$backup/$file"
    fi
    docker cp "$repo_dir/docker/tdarr/$file" "$container:$destination/$file.new.cjs"
    docker exec "$container" node --check "$destination/$file.new.cjs"
    case "$file" in
        hevc-safe-v1.cjs | hevc-offload-v1.cjs)
            docker exec "$container" node -e '
                const fs = require("fs"), file = process.argv[1];
                const read = path => fs.readFileSync(path, "utf8").replace(/\r\n/g, "\n");
                if (fs.existsSync(file) && read(file) !== read(file + ".new.cjs")) {
                    throw Error("Versioned worker module differs; deploy a new version instead");
                }
            ' "$destination/$file"
            ;;
    esac
    docker exec "$container" chmod 644 "$destination/$file.new.cjs"
    docker exec "$container" mv "$destination/$file.new.cjs" "$destination/$file"
done
docker exec --user abc "$container" node "$destination/install-offload-flow.cjs" "$@"
