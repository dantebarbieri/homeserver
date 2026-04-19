#!/bin/sh
# Bridges openzim-mcp (stdio, advanced mode → 18 tools) to Streamable HTTP via
# mcp-proxy on localhost:8081, then fronts it with proxy.py (bearer auth +
# /health) on 0.0.0.0:8080.
set -eu

mcp-proxy --port 8081 --host 127.0.0.1 --pass-environment -- \
  openzim-mcp --mode advanced /zim &
PROXY_PID=$!

uvicorn proxy:app --host 0.0.0.0 --port 8080 --no-access-log &
APP_PID=$!

trap 'kill -TERM "$PROXY_PID" "$APP_PID" 2>/dev/null' INT TERM
wait -n "$PROXY_PID" "$APP_PID"
exit_code=$?
kill -TERM "$PROXY_PID" "$APP_PID" 2>/dev/null || true
exit "$exit_code"
