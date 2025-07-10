#!/bin/bash
# deploy_update.sh
# This script updates a specified submodule, rebuilds the corresponding Docker image if there are changes,
# and performs a zero-downtime restart.

set -euo pipefail

# ====== Configuration ======
REPO_DIR="/home/danteb/homeserver"
HEALTH_WAIT=20  # Time (in seconds) to wait for the new container to be healthy

# ====== Input Validation ======
if [ $# -ne 1 ]; then
    echo "Usage: $0 <submodule-name>"
    exit 1
fi

SUBMODULE="$1"

# Ensure the submodule exists in the repo
if ! grep -q "path = $SUBMODULE" "$REPO_DIR/.gitmodules"; then
    echo "Error: Submodule '$SUBMODULE' is not found in .gitmodules."
    exit 1
fi

echo "----- Deployment Script Started at $(date) for submodule '$SUBMODULE' -----"

# Go to the repository root
cd "$REPO_DIR"

# --- Step 1: Check and update the submodule ---
echo "[1/4] Checking for updates in '$SUBMODULE'..."
old_commit=$(cd "$SUBMODULE" && git rev-parse HEAD)

git submodule update --remote "$SUBMODULE"

new_commit=$(cd "$SUBMODULE" && git rev-parse HEAD)

if [ "$old_commit" = "$new_commit" ]; then
    echo "No updates found for '$SUBMODULE' (still at commit $old_commit). Exiting."
    exit 0
fi

echo "'$SUBMODULE' updated from $old_commit to $new_commit."

# --- Step 2: Rebuild the Docker image ---
echo "[2/4] Rebuilding Docker image with the updated submodule..."
docker compose build "$SUBMODULE"

# --- Step 3: Deploy with zero downtime ---
SERVICE_NAME=$(echo "$SUBMODULE" | tr '/' '_')  # Convert paths to valid service names

echo "[3/4] Deploying new container instance (scaling to 2 instances)..."
docker compose up -d --scale "$SERVICE_NAME"=2 "$SERVICE_NAME"

echo "Waiting ${HEALTH_WAIT} seconds for the new container to become healthy..."
sleep "$HEALTH_WAIT"

echo "[4/4] Scaling back down to 1 instance to complete the deployment..."
docker compose up -d --scale "$SERVICE_NAME"=1 "$SERVICE_NAME"

echo "Deployment complete at $(date). New container (commit $new_commit) is running."
echo "----- Deployment Script Finished -----"