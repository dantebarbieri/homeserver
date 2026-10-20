#!/bin/sh
# Run LibreOffice with a throwaway user profile so concurrent conversions don't
# collide on the shared one (they otherwise fail silently).
profile="$(mktemp -d /tmp/lo-profile.XXXXXX)" || exit 1
trap 'rm -rf "$profile"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
/usr/lib/libreoffice/program/soffice "-env:UserInstallation=file://$profile" "$@"
