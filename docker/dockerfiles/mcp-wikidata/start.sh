#!/bin/sh
# Local-fallback Wikidata MCP server (zzaebok/mcp-wikidata, stdio).
# Primary route from the Pi is wd-mcp.wmcloud.org via mcp-remote — this
# container exists for resilience when wmcloud is unreachable.
set -eu

mcp-proxy --port 8081 --host 127.0.0.1 --pass-environment -- \
  python /opt/mcp-wikidata/src/server.py &
PROXY_PID=$!

uvicorn proxy:app --host 0.0.0.0 --port 8080 --no-access-log &
APP_PID=$!

trap 'kill -TERM "$PROXY_PID" "$APP_PID" 2>/dev/null' INT TERM
wait -n "$PROXY_PID" "$APP_PID"
exit_code=$?
kill -TERM "$PROXY_PID" "$APP_PID" 2>/dev/null || true
exit "$exit_code"
