#!/bin/bash
# deploy_update.sh
# This script updates the danteb.com submodule, rebuilds the docker image if there are changes,
# and performs a zero-downtime restart by temporarily scaling out the service.

set -euo pipefail

# ====== Configuration ======
# Change this to the full path of your git repository (where .gitmodules and docker-compose.yml reside)
REPO_DIR="/home/danteb/homeserver"

# (Optional) Time (in seconds) to wait for the new container to start and be healthy.
HEALTH_WAIT=20

# ====== Script Start ======
echo "----- Deployment Script Started at $(date) -----"

# Go to the repository root
cd "$REPO_DIR"

# --- Step 1: Check and update the submodule ---
echo "[1/4] Checking for updates in the danteb.com submodule..."
# Get the current commit hash of the submodule
old_commit=$(cd danteb.com && git rev-parse HEAD)

# Update the submodule to track the remote branch
git submodule update --remote danteb.com

# Get the new commit hash after update
new_commit=$(cd danteb.com && git rev-parse HEAD)

if [ "$old_commit" = "$new_commit" ]; then
    echo "No updates found for danteb.com (still at commit $old_commit). Exiting."
    exit 0
fi

echo "danteb.com updated from $old_commit to $new_commit."

# (Optional) If you want the main repo to record the new submodule commit, uncomment:
# git add danteb.com
# git commit -m "Update danteb.com submodule to $new_commit"
# git push

# --- Step 2: Rebuild the Docker image ---
echo "[2/4] Rebuilding Docker image with the updated submodule..."
# The --build flag forces a rebuild of the image.

# --- Step 3: Deploy with zero downtime ---
# For zero downtime, we temporarily scale the service to 2 instances so that the new container can start
# while the old one is still serving traffic.
# NOTE: To enable scaling, remove 'container_name: danteb' from your docker-compose.yml service definition.
echo "[3/4] Deploying new container instance (scaling to 2 instances)..."
docker-compose up -d --build --scale danteb=2 danteb

echo "Waiting ${HEALTH_WAIT} seconds for the new container to become healthy..."
sleep "$HEALTH_WAIT"

# Now scale back down to 1 instance, which removes one of the containers.
echo "[4/4] Scaling back down to 1 instance to complete the deployment..."
docker-compose up -d --scale danteb=1 danteb

echo "Deployment complete at $(date). New container (commit $new_commit) is running."
echo "----- Deployment Script Finished -----"