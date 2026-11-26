#!/bin/sh
# Test the modem proxy with synthetic data on loopback, in an isolated NPM image.
set -eu
if [ "${1:-}" != --inside ]; then
    root=$(dirname "$0")/..
    tar -C "$root" -cf - scripts/device-admin-config.sh nginx/device-admin.conf.template \
        nginx/modem-auth.conf tests/test-device-admin.sh |
        docker run --rm --pull never --network none -i --entrypoint sh \
            "${NPM_TEST_IMAGE:-jc21/nginx-proxy-manager:latest}" -ec \
            'cd /tmp && tar -xf - && sh tests/test-device-admin.sh --inside'
    exit
fi

mkdir -p /var/cache/nginx /var/log/nginx /snippets
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=fixture \
    -addext subjectAltName=DNS:modem.danteb.com -keyout key -out crt >/dev/null 2>&1
printf '%s\n' 'auth_request /internal/authelia/authz;' > /snippets/authelia-authrequest.conf
cat > fixture.conf <<'EOF'
user nobody nogroup;
pid /tmp/fixture.pid;
events {}
http {
    access_log off;
    ssl_certificate /tmp/crt;
    ssl_certificate_key /tmp/key;
    server { listen 443 ssl default_server; return 421; }
    server {
        listen 127.0.0.1:8101;
        underscores_in_headers on;
        location / { content_by_lua_block {
            local h = ngx.req.get_headers()
            if h.hnap_auth or h.soapaction or h.cookie ~= "authelia_session=fixture" then
                return ngx.exit(403)
            end
            return ngx.exit(204)
        } }
    }
    server {
        listen 127.0.0.1:8102;
        underscores_in_headers on;
        location = /HNAP1/ { content_by_lua_block {
            local h = ngx.req.get_headers()
            ngx.print(table.concat({h.hnap_auth or "", h.soapaction or "", h.cookie or "",
                h.host or "", h.origin or "", h.referer or ""}, "|"))
        } }
    }
    server { listen 443 ssl; server_name modem.danteb.com;
EOF
sh scripts/device-admin-config.sh modem | sed \
    -e 's|http://authelia:9091/api/authz/auth-request|http://127.0.0.1:8101/auth|' \
    -e 's|proxy_pass https://192.168.100.1;|proxy_pass http://127.0.0.1:8102;|' \
    -e 's|/data/device-admin/modem-ca.pem|/tmp/crt|' >> fixture.conf
printf '%s\n' '    }' '}' >> fixture.conf
nginx -p /tmp -c /tmp/fixture.conf
trap 'nginx -p /tmp -c /tmp/fixture.conf -s quit' EXIT
request() {
    curl --noproxy '*' --cacert /tmp/crt --resolve modem.danteb.com:443:127.0.0.1 \
        -sS -X POST -H 'HNAP_AUTH: synthetic' -H 'SOAPAction: action' \
        "$@" https://modem.danteb.com/HNAP1/
}
[ "$(request -o /dev/null -w '%{http_code}')" = 403 ]
cookies='authelia_session=fixture; uid=example; PrivateKey=dummy; authelia_session=duplicate'
for origin in https://modem.danteb.com https://other.invalid; do
    expected=$origin
    if [ "$origin" = https://modem.danteb.com ]; then expected=https://192.168.100.1; fi
    received=$(request -f -b "$cookies" -H "Origin: $origin" -e "$origin/page")
    [ "$received" = "synthetic|action|uid=example; PrivateKey=dummy|192.168.100.1|$expected|$expected/page" ]
done
echo 'HNAP header forwarding, authorization, cookie isolation and origin checks passed.'
