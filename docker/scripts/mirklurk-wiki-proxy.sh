#!/bin/sh
set -eu

# Point mirklurk.wiki's NPM Advanced config at nginx/cloudflare-real-ip.conf so
# NPM logs (and the wiki sees) real visitors instead of Cloudflare edges.
# Same pattern as mirklurk-map-proxy.sh: NPM's REST API with the credentials
# already inside bmc-ip-monitor; no database edits or generated-config patches.
mode="${1:---check}"
case "$mode" in --check|--apply) ;; *) echo "Usage: $0 [--check|--apply]" >&2; exit 1 ;; esac
if [ "${WIKI_PROXY_INNER:-}" != 1 ]; then
  exec docker exec -i -e WIKI_PROXY_INNER=1 bmc-ip-monitor sh -s -- "$mode" < "$0"
fi

config='include /data/custom/cloudflare-real-ip.conf;'
: "${NPM_HOST:?}" "${NPM_PORT:?}" "${NPM_EMAIL:?}" "${NPM_PASSWORD:?}"
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
  [.[] | select(.domain_names | index("mirklurk.wiki"))] |
  if length == 1 then .[0] else error("Expected exactly one wiki proxy host") end |
  if .domain_names == ["mirklurk.wiki"] and
     .forward_scheme == "http" and .forward_host == "mirklurk" and
     .forward_port == 80 and .enabled == true and .certificate_id > 0 and
     .access_list_id == 0 and .caching_enabled == false and
     ((.locations // []) | length) == 0
  then . else error("Unexpected wiki proxy routing; review before changing") end')
id=$(printf '%s' "$host" | jq -r '.id')
current=$(printf '%s' "$host" | jq -r '.advanced_config // ""')
if [ "$current" = "$config" ]; then
  echo "Wiki proxy $id already trusts CF-Connecting-IP from Cloudflare only."
  exit 0
fi
if [ -n "$current" ]; then
  echo "Wiki proxy has unrecognized Advanced configuration; refusing to overwrite." >&2
  exit 1
fi
if [ "$mode" = --check ]; then
  echo "Wiki proxy $id routing verified; real-IP configuration still needs --apply."
  exit 0
fi
payload=$(printf '%s' "$host" | jq -c --arg config "$config" '{
  domain_names, forward_scheme, forward_host, forward_port, certificate_id,
  ssl_forced, hsts_enabled, hsts_subdomains, http2_support, block_exploits,
  caching_enabled, allow_websocket_upgrade, access_list_id, locations,
  advanced_config: $config
}')
result=$(request PUT "/nginx/proxy-hosts/$id" "$payload")
printf '%s' "$result" | jq -e --arg config "$config" \
  '.advanced_config == $config and .meta.nginx_online == true' >/dev/null
echo "Wiki proxy $id updated through NPM; nginx accepted the configuration."
