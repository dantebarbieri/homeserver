#!/bin/bash
# deploy-update.sh
# Pulls the latest monorepo changes, rebuilds the specified Docker service
# if there are changes, and performs a zero-downtime restart.

set -euo pipefail

# ====== Configuration ======
REPO_DIR="/srv/homeserver"
HEALTH_WAIT=20  # Time (in seconds) to wait for the new container to be healthy

# ====== Input Validation ======
if [ $# -ne 1 ]; then
    echo "Usage: $0 <service-name>"
    exit 1
fi

SERVICE="$1"

echo "----- Deployment Script Started at $(date) for service '$SERVICE' -----"

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

# --- Step 3: Deploy with zero downtime ---
echo "[3/4] Deploying new container instance (scaling to 2 instances)..."
docker compose up -d --scale "$SERVICE"=2 "$SERVICE"

echo "Waiting ${HEALTH_WAIT} seconds for the new container to become healthy..."
sleep "$HEALTH_WAIT"

echo "[4/4] Scaling back down to 1 instance to complete the deployment..."
docker compose up -d --scale "$SERVICE"=1 "$SERVICE"

echo "Deployment complete at $(date). New container (commit $new_commit) is running."
echo "----- Deployment Script Finished -----"
