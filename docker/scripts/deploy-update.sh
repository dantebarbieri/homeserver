#!/bin/bash
# deploy-update.sh
# Pulls the latest monorepo changes, rebuilds the specified Docker service,
# and recreates it behind a health gate.
#
# Usage:
#   deploy-update.sh <service>              # pull, rebuild, deploy
#   deploy-update.sh --no-pull <service>    # deploy the working tree as-is
#
# WHY THERE IS NO BLUE-GREEN PATH
# An earlier version tried `--scale <svc>=2` for a zero-downtime swap. That
# cannot work here: Compose refuses a second replica for any service with an
# explicit `container_name:`, which is every service in this repo. Worse, the
# scale-down step retires the *highest-numbered* replica — the new one that
# just passed its health check — leaving the old container to be recreated
# without any gate. A swap that silently keeps the unvalidated container is
# more dangerous than a brief restart, so the path is gone rather than
# half-fixed. Real zero-downtime would need the service to drop
# `container_name:` and an NPM upstream swap; revisit then.

set -euo pipefail

# ====== Configuration ======
REPO_DIR="/srv/homeserver"
HEALTH_TIMEOUT=90   # Max seconds to wait for the container to report healthy
POLL_INTERVAL=3     # Seconds between health polls

# ====== Argument Parsing ======
DO_PULL=true
SERVICE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --no-pull)
            DO_PULL=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--no-pull] <service-name>"
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--no-pull] <service-name>" >&2
            exit 1
            ;;
        *)
            if [ -n "$SERVICE" ]; then
                echo "ERROR: only one service may be given (got '$SERVICE' and '$1')." >&2
                exit 1
            fi
            SERVICE="$1"
            shift
            ;;
    esac
done

if [ -z "$SERVICE" ]; then
    echo "Usage: $0 [--no-pull] <service-name>" >&2
    exit 1
fi

echo "----- Deployment Script Started at $(date) for service '$SERVICE' -----"

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
# The pull happens before the service is validated, because a service added by
# the incoming commit does not exist in the working tree yet — validating first
# would reject it as unknown.
cd "$REPO_DIR"
old_commit=$(git rev-parse HEAD)

if [ "$DO_PULL" = true ]; then
    echo "[1/4] Pulling latest changes..."
    git pull
    new_commit=$(git rev-parse HEAD)

    if [ "$old_commit" = "$new_commit" ]; then
        echo "No updates found (still at commit $old_commit)."
        echo "Nothing to deploy. Use --no-pull to force a redeploy of the current tree."
        exit 0
    fi

    echo "Updated from $old_commit to $new_commit."
else
    new_commit="$old_commit"
    echo "[1/4] Skipping pull (--no-pull); deploying working tree at $new_commit."
fi

# --- Step 2: Validate the service exists in the (now current) config ---
echo "[2/4] Validating service '$SERVICE'..."
cd "$REPO_DIR/docker"

if ! docker compose config --services | grep -qx "$SERVICE"; then
    echo "ERROR: '$SERVICE' is not a service in this compose project." >&2
    echo "Available services:" >&2
    docker compose config --services | sed 's/^/  /' >&2
    exit 1
fi

# --- Step 3: Rebuild the Docker image ---
echo "[3/4] Rebuilding Docker image for '$SERVICE'..."
docker compose build "$SERVICE"

# --- Step 4: Recreate behind a health gate ---
echo "[4/4] Recreating '$SERVICE'..."
docker compose up -d --force-recreate "$SERVICE"

cid=$(docker compose ps -q "$SERVICE")
if [ -z "$cid" ]; then
    echo "ERROR: '$SERVICE' has no container after recreate." >&2
    docker compose logs --tail 50 "$SERVICE" >&2
    exit 1
fi

echo "Waiting for '$SERVICE' ($cid) to become healthy..."

if ! wait_for_health "$cid"; then
    echo "" >&2
    echo "DEPLOYMENT FAILED — '$SERVICE' did not come up cleanly." >&2
    echo "Recent logs:" >&2
    docker compose logs --tail 50 "$SERVICE" >&2
    if [ "$DO_PULL" = true ]; then
        echo "" >&2
        echo "To roll back and redeploy the previous commit:" >&2
        echo "  git -C $REPO_DIR reset --hard $old_commit" >&2
        echo "  $0 --no-pull $SERVICE" >&2
        echo "" >&2
        echo "(--no-pull is required: without it the redeploy would pull the" >&2
        echo " failed commit straight back in and undo the reset.)" >&2
    fi
    exit 1
fi

if [ "$SERVICE" = "plex" ]; then
    echo "Verifying Plex hardware transcoding..."
    if ! bash "$REPO_DIR/docker/scripts/check-plex-hwaccel.sh"; then
        echo "DEPLOYMENT FAILED — Plex is healthy but CUDA/NVENC is unavailable." >&2
        exit 1
    fi
fi

echo "Deployment complete at $(date). '$SERVICE' is running at commit $new_commit."
echo "----- Deployment Script Finished -----"
