#!/bin/sh
set -eu

# Same supported API path as configure-recipe-app-proxies.sh. Credentials stay
# inside the existing monitor; no database edits or generated-config patches.
mode="${1:---check}"
case "$mode" in --check|--apply) ;; *) echo "Usage: $0 [--check|--apply]" >&2; exit 1 ;; esac
if [ "${MAP_PROXY_INNER:-}" != 1 ]; then
  config=$(cat "$(dirname "$0")/../nginx/mirklurk-map-npm.conf")
  exec docker exec -i -e MAP_PROXY_INNER=1 -e MAP_PROXY_CONFIG="$config" \
    bmc-ip-monitor sh -s -- "$mode" < "$0"
fi

: "${NPM_HOST:?}" "${NPM_PORT:?}" "${NPM_EMAIL:?}" "${NPM_PASSWORD:?}" "${MAP_PROXY_CONFIG:?}"
api="http://${NPM_HOST}:${NPM_PORT}/api"
login=$(jq -cn '{identity: env.NPM_EMAIL, secret: env.NPM_PASSWORD}')
token=$(curl -fsS -X POST "$api/tokens" -H 'Content-Type: application/json' \
  --data-binary "$login" | jq -er '.token')
request() {
  curl -fsS -X "$1" "$api$2" -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' ${3:+--data-binary} ${3:+"$3"}
}
hosts=$(request GET /nginx/proxy-hosts)
host=$(printf '%s' "$hosts" | jq -ce '
  [.[] | select(.domain_names | index("map.mirklurk.danteb.com"))] |
  if length == 1 then .[0] else error("Expected exactly one map proxy host") end |
  if .domain_names == ["map.mirklurk.danteb.com"] and
     .forward_scheme == "http" and .forward_host == "mirklurk-map" and
     .forward_port == 8080 and .enabled == true and .certificate_id > 0 and
     .access_list_id == 0 and .caching_enabled == false and
     ((.locations // []) | length) == 0
  then . else error("Unexpected map proxy routing; review before changing") end')
id=$(printf '%s' "$host" | jq -r '.id')
current=$(printf '%s' "$host" | jq -r '.advanced_config // ""')
if [ "$current" = "$MAP_PROXY_CONFIG" ]; then
  echo "Map proxy $id already has the reviewed privacy configuration."
  exit 0
fi
if [ -n "$current" ]; then
  echo "Map proxy has unrecognized Advanced configuration; refusing to overwrite." >&2
  exit 1
fi
if [ "$mode" = --check ]; then
  echo "Map proxy $id routing verified; privacy configuration still needs --apply."
  exit 0
fi
payload=$(printf '%s' "$host" | jq -c --arg config "$MAP_PROXY_CONFIG" '{
  domain_names, forward_scheme, forward_host, forward_port, certificate_id,
  ssl_forced, hsts_enabled, hsts_subdomains, http2_support, block_exploits,
  caching_enabled, allow_websocket_upgrade, access_list_id, locations,
  advanced_config: $config
}')
result=$(request PUT "/nginx/proxy-hosts/$id" "$payload")
printf '%s' "$result" | jq -e --arg config "$MAP_PROXY_CONFIG" \
  '.advanced_config == $config and .meta.nginx_online == true' >/dev/null
echo "Map proxy $id updated through NPM; nginx accepted the configuration."
