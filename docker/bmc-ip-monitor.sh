#!/bin/sh
set -eu

NPM_HOST=${NPM_HOST:-nginxproxymanager}
NPM_PORT=${NPM_PORT:-81}
NPM_API="http://${NPM_HOST}:${NPM_PORT}/api"
PROXY_DOMAIN=${PROXY_DOMAIN:-ipmi.danteb.com}
CHECK_INTERVAL=${CHECK_INTERVAL:-900}
NTFY_URL=${NTFY_URL:-https://ntfy.danteb.com}
NTFY_TOPIC=${NTFY_TOPIC:-homeserver-alerts}

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

log "[bmc-ip-monitor] starting (domain=${PROXY_DOMAIN}, interval=${CHECK_INTERVAL}s)"

while :; do
  # Step 1: Get current BMC IP via IPMI system interface
  BMC_IP=$(ipmitool lan print 1 2>/dev/null \
    | grep "IP Address" | grep -v "Source" | awk '{print $NF}') || true

  if [ -z "$BMC_IP" ]; then
    log "ERROR: could not read BMC IP via ipmitool"
    ntfy "BMC IP Monitor Failed" "Could not read BMC IP via ipmitool" "high" "warning,computer"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  # Step 2: Skip if unchanged
  if [ "$BMC_IP" = "$LAST_IP" ]; then
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "BMC IP is ${BMC_IP} (was: ${LAST_IP:-unknown})"

  # Step 3: Authenticate to NPM
  TOKEN=$(npm_login) || true
  if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    log "ERROR: NPM API authentication failed"
    ntfy "BMC IP Monitor: NPM Auth Failed" "Could not authenticate to NPM API" "high" "warning,computer"
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
    ntfy "BMC IP Monitor: Proxy Host Missing" \
      "No proxy host found for ${PROXY_DOMAIN} in NPM" "high" "warning,computer"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  HOST_ID=$(echo "$HOST_JSON" | jq -r '.id')
  CURRENT_HOST=$(echo "$HOST_JSON" | jq -r '.forward_host')
  CURRENT_ADVANCED=$(echo "$HOST_JSON" | jq -r '.advanced_config // ""')

  # Extract IP from proxy_pass line in advanced_config
  ADVANCED_IP=$(echo "$CURRENT_ADVANCED" | grep -oE 'proxy_pass https?://[^:]+' \
    | sed 's|proxy_pass https\?://||') || true

  # Step 5: Compare and update if different
  if [ "$CURRENT_HOST" = "$BMC_IP" ] && [ "$ADVANCED_IP" = "$BMC_IP" ]; then
    log "NPM proxy host ${HOST_ID} already points to ${BMC_IP} — no update needed"
    LAST_IP="$BMC_IP"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "Updating NPM proxy host ${HOST_ID}: ${CURRENT_HOST} -> ${BMC_IP}"

  # Build updated advanced_config
  if [ -n "$ADVANCED_IP" ] && [ "$ADVANCED_IP" != "$BMC_IP" ]; then
    NEW_ADVANCED=$(echo "$CURRENT_ADVANCED" | sed "s|${ADVANCED_IP}|${BMC_IP}|g")
  else
    NEW_ADVANCED="$CURRENT_ADVANCED"
  fi

  # Build PUT payload with required fields
  UPDATED_JSON=$(echo "$HOST_JSON" | jq \
    --arg ip "$BMC_IP" \
    --arg adv "$NEW_ADVANCED" \
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
      advanced_config: $adv,
      meta: .meta,
      locations: .locations
    }')

  RESULT=$(curl -sf -X PUT "${NPM_API}/nginx/proxy-hosts/${HOST_ID}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$UPDATED_JSON") || true

  if [ -z "$RESULT" ]; then
    log "ERROR: failed to update NPM proxy host ${HOST_ID}"
    ntfy "BMC IP Monitor: Update Failed" \
      "Failed to update NPM proxy host for ${PROXY_DOMAIN}. BMC IP: ${BMC_IP}" \
      "high" "warning,computer"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  log "Successfully updated NPM proxy host ${HOST_ID} to ${BMC_IP}"
  ntfy "BMC IP Changed" \
    "IPMI proxy updated: ${CURRENT_HOST} -> ${BMC_IP} (${PROXY_DOMAIN})" \
    "default" "shuffle,computer"

  LAST_IP="$BMC_IP"
  sleep "$CHECK_INTERVAL"
done
