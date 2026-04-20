#!/bin/sh
# wikipedia-mcp speaks Streamable HTTP natively and supports static-bearer
# auth via --auth-mode. The package has no User-Agent customization knob;
# Wikimedia rate-limit compliance relies on traffic volume staying low.
set -eu

TOKEN=$(cat "$AUTH_TOKEN_FILE")

exec wikipedia-mcp \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8080 \
  --auth-mode static \
  --auth-token "$TOKEN"
