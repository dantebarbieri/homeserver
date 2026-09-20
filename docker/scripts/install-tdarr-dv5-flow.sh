#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
container="${TDARR_CONTAINER:-tdarr}"
destination=/app/server/Tdarr/Custom

if [[ "${1:-}" != "--apply" || "$#" -gt 2 || ( "$#" -eq 2 && "${2:-}" != "--enable" ) ]]; then
    echo "Usage: $0 --apply [--enable]" >&2
    echo "Installs the versioned module and API flow; a new library starts disabled." >&2
    echo "--enable starts the movie watcher and configures one GPU worker." >&2
    exit 2
fi

if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]]; then
    echo "ERROR: Tdarr container is not running." >&2
    exit 1
fi

node_limits="$(docker exec "$container" node -e '
    (async () => {
        const fs = require("fs");
        const config = JSON.parse(fs.readFileSync("/app/configs/Tdarr_Node_Config.json"));
        const key = process.env.apiKey || config.apiKey;
        if (!key) throw Error("Tdarr API key is missing");
        const response = await fetch("http://127.0.0.1:8265/api/v2/get-nodes", {
            headers: { "x-api-key": key }, signal: AbortSignal.timeout(30000),
        });
        if (!response.ok) throw Error(`Node API HTTP ${response.status}`);
        const nodes = Object.values(await response.json());
        if (nodes.some(node => Object.keys(node.workers || {}).length)) {
            throw Error("Tdarr has active workers; wait before updating the module");
        }
        console.log(nodes.length);
    })().catch(error => { console.error(error.message); process.exit(1); });
')"
if [[ "$node_limits" != 1 ]]; then
    echo "ERROR: This deployment supports one colocated Tdarr node only." >&2
    exit 1
fi

docker exec "$container" mkdir -p "$destination"
docker exec "$container" chown --reference=/app/server/Tdarr "$destination"
for file in dv5-sidecar.cjs install-flow.cjs; do
    docker cp "$repo_dir/docker/tdarr/$file" "$container:$destination/$file.new.cjs"
    docker exec "$container" node --check "$destination/$file.new.cjs"
    docker exec "$container" mv "$destination/$file.new.cjs" "$destination/$file"
done
docker exec --user abc "$container" node "$destination/install-flow.cjs" "$@"
