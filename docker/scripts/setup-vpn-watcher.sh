#!/bin/sh
set -e

echo "🔧 Setting up VPN Watcher..."

# Get the docker/ directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DOCKER_DIR"

# Source the .env file to get DATA path
if [ -f .env ]; then
    set +e  # Temporarily disable exit on error
    set -a
    . ./.env 2>/dev/null
    set +a
    set -e  # Re-enable exit on error
else
    echo "⚠️  Warning: .env file not found. Using sample.env values."
    set +e  # Temporarily disable exit on error
    set -a
    . ./sample.env 2>/dev/null
    set +a
    set -e  # Re-enable exit on error
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p "${DATA}/vpn-watcher/logs"

# Copy and set permissions for vpn-watcher script
echo "📋 Copying vpn-watcher.sh to ${DATA}/vpn-watcher/..."
cp -f "$SCRIPT_DIR/vpn-watcher.sh" "${DATA}/vpn-watcher/vpn-watcher.sh"
chmod +x "${DATA}/vpn-watcher/vpn-watcher.sh"

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Review the changes in docker-compose.yml"
echo "2. Run: docker compose up -d vpn-watcher"
echo "3. Check logs: docker logs -f vpn-watcher"
echo ""
echo "The vpn-watcher will now automatically recreate qBittorrent when gluetun becomes healthy."
