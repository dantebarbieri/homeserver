#!/bin/sh
set -eu

NPM_API="http://${NPM_HOST}:${NPM_PORT}/api"

log() { echo "[$(date -Iseconds)] $*"; }

ntfy() {
  # Usage: ntfy "Title" "Message" [priority] [tags]
  TITLE="$1"
  MESSAGE="$2"
  PRIORITY="${3:-default}"
  TAGS="${4:-}"
  curl -s \
    -H "Title: $TITLE" \
    -H "Priority: $PRIORITY" \
    -H "Tags: $TAGS" \
    -d "$MESSAGE" \
    "${NTFY_URL}/${NTFY_TOPIC}" >/dev/null || log "WARNING: ntfy send failed"
}

npm_login() {
  curl -sf -X POST "${NPM_API}/tokens" \
    -H "Content-Type: application/json" \
    -d "{\"identity\":\"${NPM_EMAIL}\",\"secret\":\"${NPM_PASSWORD}\"}" \
    | jq -r '.token'
}

LAST_IP=""
FAIL_COUNT=0
MAX_FAILURES="${MAX_FAILURES:-3}"

log "[pi-ip-monitor] starting (domain=${PROXY_DOMAIN}, mac=${TARGET_MAC}, subnet=${SCAN_SUBNET}, interval=${CHECK_INTERVAL}s, max_failures=${MAX_FAILURES})"

while :; do
  # Step 1: Discover Pi IP via ARP scan for target MAC address
  PI_IP=$(nmap -sn "$SCAN_SUBNET" 2>/dev/null \
    | grep -B2 -i "$TARGET_MAC" \
    | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}') || true

  if [ -z "$PI_IP" ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    log "WARNING: could not find device with MAC ${TARGET_MAC} on ${SCAN_SUBNET} (failure ${FAIL_COUNT}/${MAX_FAILURES})"
    if [ "$FAIL_COUNT" -ge "$MAX_FAILURES" ]; then
      ntfy "Pi Unreachable" \
        "Could not find device ${TARGET_MAC} on ${SCAN_SUBNET} for ${FAIL_COUNT} consecutive checks (~$(( FAIL_COUNT * CHECK_INTERVAL / 60 )) min)" \
        "high" "warning,raspberry"
    fi
    sleep "$CHECK_INTERVAL"
    continue
  fi

  # Device found — reset failure counter
  FAIL_COUNT=0

  # Step 2: Skip if unchanged
  if [ "$PI_IP" = "$LAST_IP" ]; then
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "Pi IP is ${PI_IP} (was: ${LAST_IP:-unknown})"

  # Step 3: Authenticate to NPM
  TOKEN=$(npm_login) || true
  if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    log "ERROR: NPM API authentication failed"
    ntfy "Pi IP Monitor: NPM Auth Failed" "Could not authenticate to NPM API" "high" "warning,raspberry"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  # Step 4: Find proxy host by domain name
  ALL_HOSTS=$(curl -sf "${NPM_API}/nginx/proxy-hosts" \
    -H "Authorization: Bearer $TOKEN") || true

  if [ -z "$ALL_HOSTS" ]; then
    log "ERROR: could not fetch proxy hosts from NPM"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  HOST_JSON=$(echo "$ALL_HOSTS" | jq -c ".[] | select(.domain_names[] == \"${PROXY_DOMAIN}\")")

  if [ -z "$HOST_JSON" ]; then
    log "ERROR: proxy host for ${PROXY_DOMAIN} not found in NPM"
    ntfy "Pi IP Monitor: Proxy Host Missing" \
      "No proxy host found for ${PROXY_DOMAIN} in NPM" "high" "warning,raspberry"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  HOST_ID=$(echo "$HOST_JSON" | jq -r '.id')
  CURRENT_HOST=$(echo "$HOST_JSON" | jq -r '.forward_host')

  # Step 5: Compare and update if different
  if [ "$CURRENT_HOST" = "$PI_IP" ]; then
    log "NPM proxy host ${HOST_ID} already points to ${PI_IP} — no update needed"
    LAST_IP="$PI_IP"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "Updating NPM proxy host ${HOST_ID}: ${CURRENT_HOST} -> ${PI_IP}"

  # Build PUT payload with required fields
  UPDATED_JSON=$(echo "$HOST_JSON" | jq \
    --arg ip "$PI_IP" \
    '{
      domain_names: .domain_names,
      forward_scheme: .forward_scheme,
      forward_host: $ip,
      forward_port: .forward_port,
      certificate_id: .certificate_id,
      ssl_forced: (.ssl_forced // false),
      hsts_enabled: (.hsts_enabled // false),
      hsts_subdomains: (.hsts_subdomains // false),
      http2_support: (.http2_support // false),
      block_exploits: (.block_exploits // false),
      caching_enabled: (.caching_enabled // false),
      allow_websocket_upgrade: (.allow_websocket_upgrade // false),
      access_list_id: (.access_list_id // 0),
      advanced_config: (.advanced_config // ""),
      meta: .meta,
      locations: .locations
    }')

  RESULT=$(curl -sf -X PUT "${NPM_API}/nginx/proxy-hosts/${HOST_ID}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$UPDATED_JSON") || true

  if [ -z "$RESULT" ]; then
    log "ERROR: failed to update NPM proxy host ${HOST_ID}"
    ntfy "Pi IP Monitor: Update Failed" \
      "Failed to update NPM proxy host for ${PROXY_DOMAIN}. Pi IP: ${PI_IP}" \
      "high" "warning,raspberry"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "Successfully updated NPM proxy host ${HOST_ID} to ${PI_IP}"
  ntfy "Pi IP Changed" \
    "OpenClaw proxy updated: ${CURRENT_HOST} -> ${PI_IP} (${PROXY_DOMAIN})" \
    "default" "shuffle,raspberry"

  LAST_IP="$PI_IP"
  sleep "$CHECK_INTERVAL"
done
