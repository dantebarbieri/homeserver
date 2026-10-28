#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != --apply || "$#" -ne 1 ]]; then
    echo "Usage: $0 --apply" >&2
    exit 2
fi

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
destination=/app/server/Tdarr/Custom
docker exec tdarr mkdir -p "$destination/backups"
backup="$destination/backups/modules-$(date +%s)"
docker exec tdarr mkdir "$backup"
for file in dv5-sidecar.cjs install-flow.cjs hevc-safe-v1.cjs install-safe-flows.cjs maintenance.cjs reconcile-sidecars.cjs recover-policy-errors.cjs; do
    if docker exec tdarr test -f "$destination/$file"; then
        docker exec tdarr cp -p "$destination/$file" "$backup/$file"
    fi
    docker cp "$repo_dir/docker/tdarr/$file" "tdarr:$destination/$file.new.cjs"
    docker exec tdarr node --check "$destination/$file.new.cjs"
    if [[ "$file" == hevc-safe-v1.cjs ]]; then
        docker exec tdarr node -e '
            const fs = require("fs"), file = process.argv[1];
            const read = path => fs.readFileSync(path, "utf8").replace(/\r\n/g, "\n");
            if (fs.existsSync(file) && read(file) !== read(file + ".new.cjs")) {
                throw Error("Versioned worker module differs; deploy a new version instead");
            }
        ' "$destination/$file"
    fi
    docker exec tdarr chmod 644 "$destination/$file.new.cjs"
    docker exec tdarr mv "$destination/$file.new.cjs" "$destination/$file"
done
docker exec --user abc tdarr node "$destination/install-safe-flows.cjs" --apply
