#!/bin/sh
set -eu

if [ "${ATLAS_PROXY_INNER:-}" != 1 ]; then
  docker exec -i -e ATLAS_PROXY_INNER=1 bmc-ip-monitor sh -s < "$0"
  docker exec nginxproxymanager nginx -t
  exit 0
fi
: "${NPM_HOST:?}" "${NPM_PORT:?}" "${NPM_EMAIL:?}" "${NPM_PASSWORD:?}"
api="http://${NPM_HOST}:${NPM_PORT}/api"
login=$(jq -cn '{identity:env.NPM_EMAIL,secret:env.NPM_PASSWORD}')
token=$(curl -fsS -X POST "$api/tokens" -H 'Content-Type: application/json' --data-binary "$login" | jq -er .token)
request() {
  curl -fsS -X "$1" "$api$2" -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' ${3:+--data-binary} ${3:+"$3"}
}
hosts=$(request GET /nginx/proxy-hosts)
config='include /snippets/authelia-location.conf;
location = /metrics { return 404; }
location / {
    include /snippets/proxy.conf;
    include /snippets/authelia-authrequest.conf;
    proxy_pass $forward_scheme://$server:$port;
}'
existing=$(printf '%s' "$hosts" | jq -ce '[.[]|select(.domain_names|index("server-atlas.danteb.com"))] | if length <= 1 then . else error("Duplicate Atlas proxy hosts") end')
if [ "$(printf '%s' "$existing" | jq length)" = 1 ]; then
  printf '%s' "$existing" | jq -e --arg config "$config" '.[0] | .domain_names == ["server-atlas.danteb.com"] and .forward_host == "server-atlas" and .forward_port == 8080 and .advanced_config == $config and .enabled and .ssl_forced' >/dev/null || {
    echo "Existing Atlas proxy has unexpected settings; refusing to overwrite." >&2
    exit 1
  }
  echo "Existing Atlas proxy is configured."
  exit 0
fi
certificate=$(printf '%s' "$hosts" | jq -er '[.[]|select(.domain_names|index("dashdot.danteb.com"))][0].certificate_id | select(. > 0)')
payload=$(jq -cn --argjson certificate "$certificate" --arg config "$config" '{
  domain_names:["server-atlas.danteb.com"],forward_scheme:"http",forward_host:"server-atlas",forward_port:8080,
  certificate_id:$certificate,ssl_forced:true,hsts_enabled:true,hsts_subdomains:false,http2_support:true,
  block_exploits:true,caching_enabled:false,allow_websocket_upgrade:false,access_list_id:0,locations:[],
  advanced_config:$config,meta:{letsencrypt_agree:false,dns_challenge:false}
}')
response=$(request POST /nginx/proxy-hosts "$payload")
printf '%s' "$response" | jq -e '(.enabled == true or .enabled == 1) and .meta.nginx_online != false and .meta.nginx_online != 0' >/dev/null || {
  echo "NPM did not confirm the new route. Inspect its sanitized status:" >&2
  printf '%s' "$response" | jq '{id,enabled,nginx_online:.meta.nginx_online,nginx_err:.meta.nginx_err}' >&2
  exit 1
}
echo "Atlas proxy created with Authelia protection; /metrics is not exposed."
