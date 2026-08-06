#!/bin/bash
# deploy-update.sh
# Pulls the latest monorepo changes, rebuilds the specified Docker service,
# and restarts it — using a blue-green swap where the service supports it,
# otherwise a plain recreate with a health gate.
#
# NOTE ON SCALING: the previous version of this script always used
# `--scale <svc>=2`. That cannot work for any service declaring an explicit
# `container_name:`, which is currently every service in this repo — Compose
# refuses to create a second replica under a fixed name. The script now
# detects that case instead of failing, and both paths wait for actual health
# rather than sleeping blindly.

set -euo pipefail

# ====== Configuration ======
REPO_DIR="/srv/homeserver"
HEALTH_TIMEOUT=90   # Max seconds to wait for the container to report healthy
POLL_INTERVAL=3     # Seconds between health polls

# ====== Input Validation ======
if [ $# -ne 1 ]; then
    echo "Usage: $0 <service-name>"
    exit 1
fi

SERVICE="$1"

echo "----- Deployment Script Started at $(date) for service '$SERVICE' -----"

cd "$REPO_DIR/docker"

if ! docker compose config --services | grep -qx "$SERVICE"; then
    echo "ERROR: '$SERVICE' is not a service in this compose project." >&2
    echo "Available services:" >&2
    docker compose config --services | sed 's/^/  /' >&2
    exit 1
fi

# ====== Health helper ======
# Waits for a container to be healthy. Containers without a healthcheck only
# need to still be running after a short settle period — that is the strongest
# signal available for them, and it still catches immediate crash-on-start
# (the common failure after an image bump).
wait_for_health() {
    local cid="$1"
    local waited=0

    local has_health
    has_health=$(docker inspect --format '{{if .State.Health}}yes{{else}}no{{end}}' "$cid")

    if [ "$has_health" = "no" ]; then
        echo "  (no healthcheck defined — verifying the container stays up)"
        sleep 10
        if [ "$(docker inspect --format '{{.State.Running}}' "$cid")" = "true" ]; then
            return 0
        fi
        echo "  Container exited shortly after start." >&2
        return 1
    fi

    while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
        local status
        status=$(docker inspect --format '{{.State.Health.Status}}' "$cid")
        case "$status" in
            healthy)
                echo "  Healthy after ${waited}s."
                return 0
                ;;
            unhealthy)
                echo "  Container reported unhealthy after ${waited}s." >&2
                return 1
                ;;
        esac
        sleep "$POLL_INTERVAL"
        waited=$((waited + POLL_INTERVAL))
    done

    echo "  Timed out after ${HEALTH_TIMEOUT}s waiting for health." >&2
    return 1
}

# --- Step 1: Pull latest changes ---
echo "[1/4] Pulling latest changes..."
cd "$REPO_DIR"
old_commit=$(git rev-parse HEAD)

git pull

new_commit=$(git rev-parse HEAD)

if [ "$old_commit" = "$new_commit" ]; then
    echo "No updates found (still at commit $old_commit). Exiting."
    exit 0
fi

echo "Updated from $old_commit to $new_commit."

# --- Step 2: Rebuild the Docker image ---
echo "[2/4] Rebuilding Docker image for '$SERVICE'..."
cd "$REPO_DIR/docker"
docker compose build "$SERVICE"

# --- Step 3: Decide on a deployment strategy ---
# A service can only run two replicas if Compose is free to name them. When a
# container_name is set, the running container is named exactly that; otherwise
# Compose generates "<project>-<service>-<n>".
echo "[3/4] Selecting deployment strategy..."
running_name=$(docker compose ps --format '{{.Name}}' "$SERVICE" 2>/dev/null | head -1)
project_name=$(docker compose config --format json 2>/dev/null | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -1)
project_name="${project_name:-compose}"

if [ -n "$running_name" ] && [ "$running_name" != "${project_name}-${SERVICE}-1" ]; then
    SCALABLE=false
    echo "  '$SERVICE' uses a fixed container_name ($running_name) — using recreate."
else
    SCALABLE=true
    echo "  '$SERVICE' has no fixed container_name — using blue-green swap."
fi

# --- Step 4: Deploy ---
if [ "$SCALABLE" = true ]; then
    echo "[4/4] Starting a second instance alongside the current one..."
    docker compose up -d --no-recreate --scale "$SERVICE"=2 "$SERVICE"

    new_cid=$(docker compose ps -q "$SERVICE" | tail -1)
    echo "Waiting for the new container ($new_cid) to become healthy..."

    if ! wait_for_health "$new_cid"; then
        echo "New instance failed its health gate — rolling back to a single old instance." >&2
        docker rm -f "$new_cid" >/dev/null 2>&1 || true
        docker compose up -d --no-recreate --scale "$SERVICE"=1 "$SERVICE"
        exit 1
    fi

    echo "Scaling back down to 1 instance to retire the old container..."
    docker compose up -d --scale "$SERVICE"=1 "$SERVICE"
else
    echo "[4/4] Recreating '$SERVICE'..."
    docker compose up -d --force-recreate "$SERVICE"

    cid=$(docker compose ps -q "$SERVICE")
    echo "Waiting for '$SERVICE' ($cid) to become healthy..."

    if ! wait_for_health "$cid"; then
        echo "" >&2
        echo "DEPLOYMENT FAILED — '$SERVICE' did not come up cleanly." >&2
        echo "Recent logs:" >&2
        docker compose logs --tail 50 "$SERVICE" >&2
        echo "" >&2
        echo "To roll back the repo:  git -C $REPO_DIR reset --hard $old_commit" >&2
        echo "Then redeploy:          $0 $SERVICE" >&2
        exit 1
    fi
fi

echo "Deployment complete at $(date). '$SERVICE' is running at commit $new_commit."
echo "----- Deployment Script Finished -----"
