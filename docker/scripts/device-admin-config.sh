#!/bin/sh
# Render the NPM Advanced configuration for one of the two hardware portals.
set -eu
case "${1:-}" in
  modem) authority=192.168.100.1; name=0000BAE2ED44; login=/Login.html ;;
  router) authority=192.168.50.1:8443; name=router.asus.com; login='/Main_Login.asp?redirct=false' ;;
  *) echo "Usage: $0 modem|router" >&2; exit 1 ;;
esac
nginx_dir="$(dirname "$0")/../nginx"
echo '# NPM Advanced config. Keep an explicit location / so NPM omits its default proxy.'
if [ "$1" = modem ]; then
    cat "$nginx_dir/modem-auth.conf"
else
    echo 'include /snippets/authelia-location.conf;'
fi
sed -e "s|@DEVICE@|$1|g" -e "s|@HOST@|$1.danteb.com|g" \
    -e "s|@HOST_REGEX@|$1[.]danteb[.]com|g" -e "s|@AUTHORITY@|$authority|g" \
    -e "s|@TLS_NAME@|$name|g" -e "s|@LOGIN@|$login|g" \
    "$nginx_dir/device-admin.conf.template"
