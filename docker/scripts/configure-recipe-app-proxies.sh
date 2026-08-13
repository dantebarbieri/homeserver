#!/bin/sh

set -eu

# The BMC monitor image already contains curl + jq, has NPM credentials in its
# environment, and shares NPM's internal network. Re-execute this script there
# so credentials never leave the container or get duplicated in the repo.
if [ "${RECIPE_PROXY_INNER:-}" != "1" ]; then
  if ! docker inspect bmc-ip-monitor >/dev/null 2>&1; then
    echo "bmc-ip-monitor must be running before configuring NPM." >&2
    exit 1
  fi

  exec docker exec -i \
    -e RECIPE_PROXY_INNER=1 \
    bmc-ip-monitor sh -s < "$0"
fi

: "${NPM_HOST:?}"
: "${NPM_PORT:?}"
: "${NPM_EMAIL:?}"
: "${NPM_PASSWORD:?}"

NPM_API="http://${NPM_HOST}:${NPM_PORT}/api"
DOMAINS='[
  "gpt-sol.recipe.danteb.com",
  "gemini.recipe.danteb.com",
  "claude.recipe.danteb.com",
  "grok.recipe.danteb.com"
]'
AUTHELIA_CONFIG='include /snippets/authelia-location.conf;
include /snippets/authelia-authrequest.conf;'

TOKEN=$(curl -fsS -X POST "${NPM_API}/tokens" \
  -H "Content-Type: application/json" \
  -d "{\"identity\":\"${NPM_EMAIL}\",\"secret\":\"${NPM_PASSWORD}\"}" \
  | jq -r '.token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "NPM authentication failed." >&2
  exit 1
fi

api() {
  method="$1"
  path="$2"
  payload="${3:-}"

  if [ -n "$payload" ]; then
    curl -fsS -X "$method" "${NPM_API}${path}" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "$payload"
  else
    curl -fsS -X "$method" "${NPM_API}${path}" \
      -H "Authorization: Bearer $TOKEN"
  fi
}

CERT_ID=$(api GET "/nginx/certificates" | jq -r \
  --argjson domains "$DOMAINS" \
  '.[] | select(.provider == "letsencrypt" and ((.domain_names | sort) == ($domains | sort))) | .id' \
  | sed -n '1p')

if [ -z "$CERT_ID" ]; then
  cert_payload=$(jq -cn \
    --arg email "$NPM_EMAIL" \
    --argjson domains "$DOMAINS" \
    '{
      provider: "letsencrypt",
      nice_name: "Model recipe applications",
      domain_names: $domains,
      meta: {
        letsencrypt_email: $email,
        letsencrypt_agree: true,
        dns_challenge: false
      }
    }')
  CERT_ID=$(api POST "/nginx/certificates" "$cert_payload" | jq -r '.id')
  echo "Created shared TLS certificate $CERT_ID."
else
  echo "Using shared TLS certificate $CERT_ID."
fi

case "$CERT_ID" in
  ''|*[!0-9]*)
    echo "NPM returned an invalid certificate ID." >&2
    exit 1
    ;;
esac

configure_host() {
  domain="$1"
  upstream="$2"
  port="$3"

  hosts=$(api GET "/nginx/proxy-hosts")
  matches=$(printf '%s' "$hosts" | jq -c --arg domain "$domain" \
    '[.[] | select(.domain_names | index($domain))]')
  count=$(printf '%s' "$matches" | jq 'length')

  if [ "$count" -gt 1 ]; then
    echo "Multiple NPM proxy hosts contain $domain; refusing to choose one." >&2
    exit 1
  fi

  payload=$(jq -cn \
    --arg domain "$domain" \
    --arg upstream "$upstream" \
    --arg advanced "$AUTHELIA_CONFIG" \
    --argjson port "$port" \
    --argjson certificate_id "$CERT_ID" \
    '{
      domain_names: [$domain],
      forward_scheme: "http",
      forward_host: $upstream,
      forward_port: $port,
      certificate_id: $certificate_id,
      ssl_forced: true,
      hsts_enabled: true,
      hsts_subdomains: false,
      http2_support: true,
      block_exploits: true,
      caching_enabled: false,
      allow_websocket_upgrade: false,
      access_list_id: 0,
      advanced_config: $advanced,
      meta: {
        letsencrypt_agree: false,
        dns_challenge: false
      },
      locations: []
    }')

  if [ "$count" -eq 0 ]; then
    api POST "/nginx/proxy-hosts" "$payload" >/dev/null
    action="Created"
  else
    host_id=$(printf '%s' "$matches" | jq -r '.[0].id')
    api PUT "/nginx/proxy-hosts/${host_id}" "$payload" >/dev/null
    action="Updated"
  fi

  printf '%s %s -> %s:%s\n' "$action" "$domain" "$upstream" "$port"
}

configure_host "gpt-sol.recipe.danteb.com" "recipe-gpt-sol" 3011
configure_host "gemini.recipe.danteb.com" "recipe-gemini" 3012
configure_host "claude.recipe.danteb.com" "recipe-claude" 3013
configure_host "grok.recipe.danteb.com" "recipe-grok" 3014
