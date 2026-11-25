#!/bin/sh
set -eu

if [ "${ATTACKS_PROXY_INNER:-}" != 1 ]; then
  docker exec authelia authelia access-control check-policy --config /config/configuration.yml \
    --url https://attacks.danteb.com --username policy-probe --groups admins |
    grep -q "The policy 'two_factor'" || { echo "Configure admins-only two-factor access first." >&2; exit 1; }
  docker exec authelia authelia access-control check-policy --config /config/configuration.yml \
    --url https://attacks.danteb.com --username policy-probe --groups users |
    grep -q "The policy 'deny'" || { echo "Non-admin users must be denied." >&2; exit 1; }
  docker exec -i -e ATTACKS_PROXY_INNER=1 bmc-ip-monitor sh -s < "$0"
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
previous='include /snippets/authelia-location.conf;
location = /metrics { return 404; }
location / {
    include /snippets/proxy.conf;
    include /snippets/authelia-authrequest.conf;
    proxy_pass $forward_scheme://$server:$port;
}'
# Home-screen icons are fetched without the SSO cookie, so only these public images skip Authelia.
config='include /snippets/authelia-location.conf;
location = /metrics { return 404; }
location ~ ^/(apple-touch-icon(-precomposed)?|icon-192|icon-512)\.png$ {
    include /snippets/proxy.conf;
    proxy_pass $forward_scheme://$server:$port;
}
location / {
    include /snippets/proxy.conf;
    include /snippets/authelia-authrequest.conf;
    proxy_pass $forward_scheme://$server:$port;
}'
existing=$(printf '%s' "$hosts" | jq -c '[.[]|select(.domain_names|index("attacks.danteb.com"))]')
if [ "$(printf '%s' "$existing" | jq length)" != 0 ]; then
  expected='length == 1 and (.[0] | .domain_names == ["attacks.danteb.com"] and
    .forward_host == "attacks" and .forward_port == 8080 and
    .advanced_config == $config and .enabled and .ssl_forced)'
  if printf '%s' "$existing" | jq -e --arg config "$config" "$expected" >/dev/null; then
    echo "Attacks proxy already configured."
    exit 0
  fi
  printf '%s' "$existing" | jq -e --arg config "$previous" "$expected" >/dev/null || {
    echo "Unexpected existing attacks proxy; refusing to overwrite." >&2
    exit 1
  }
  id=$(printf '%s' "$existing" | jq -er '.[0].id')
  request PUT "/nginx/proxy-hosts/$id" "$(jq -cn --arg config "$config" '{advanced_config:$config}')" |
    jq -e --arg config "$config" '.advanced_config == $config' >/dev/null || {
    echo "NPM did not confirm the icon exemption; inspect the host before proceeding." >&2
    exit 1
  }
  echo "Attacks proxy updated: home-screen icons no longer require sign-in."
  exit 0
fi
certificates=$(request GET /nginx/certificates)
certificate=$(printf '%s' "$certificates" | jq -er '
  [.[]|select(any(.domain_names[]; . == "*.danteb.com" or . == "attacks.danteb.com"))]
  | sort_by(.expires_on) | last | .id | select(. > 0)') || {
  echo "NPM needs a certificate covering attacks.danteb.com." >&2
  exit 1
}
payload=$(jq -cn --argjson certificate "$certificate" --arg config "$config" '{
  domain_names:["attacks.danteb.com"],forward_scheme:"http",forward_host:"attacks",forward_port:8080,
  certificate_id:$certificate,ssl_forced:true,hsts_enabled:true,hsts_subdomains:false,http2_support:true,
  block_exploits:true,caching_enabled:false,allow_websocket_upgrade:false,access_list_id:0,locations:[],
  advanced_config:$config,meta:{letsencrypt_agree:false,dns_challenge:false}
}')
response=$(request POST /nginx/proxy-hosts "$payload")
printf '%s' "$response" | jq -e '
  (.enabled == true or .enabled == 1) and .meta.nginx_online != false and .meta.nginx_online != 0' >/dev/null || {
  echo "NPM did not confirm the route; inspect its status before proceeding." >&2
  exit 1
}
echo "Attacks proxy created with Authelia protection; no raw metrics or log API is exposed."
