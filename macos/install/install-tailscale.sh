#!/bin/bash
# As run on No-Face on 2026-11-21 (sudo, from a staged copy of this repo's
# macos/ and scripts/ directories). Installs the open-source tailscaled as a
# boot-time LaunchDaemon (the only macOS variant that runs before login), the
# BMC subnet-route NAT helper and the wake-pc command. Logging in to the
# tailnet is a separate, interactive step: see macos/README.md.
set -euo pipefail
[[ "$(id -u)" == 0 ]]
admin=dantebarbieri
stage=$(cd "$(dirname "$0")/../.." && pwd)

(cd /tmp && sudo -H -u "$admin" /opt/homebrew/bin/brew install tailscale)
# Copies the binary to /usr/local/bin/tailscaled; brew upgrade does not touch
# that copy, so rerun this after upgrading.
/opt/homebrew/bin/tailscaled install-system-daemon

install -d -o root -g wheel -m 755 /usr/local/libexec
install -o root -g wheel -m 755 "$stage/macos/tailscale/tailscale-bmc-route.sh" \
    /usr/local/libexec/tailscale-bmc-route.sh
plutil -lint "$stage/macos/tailscale/com.danteb.tailscale-bmc-route.plist"
install -o root -g wheel -m 644 "$stage/macos/tailscale/com.danteb.tailscale-bmc-route.plist" \
    /Library/LaunchDaemons/com.danteb.tailscale-bmc-route.plist
launchctl bootout system/com.danteb.tailscale-bmc-route 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.danteb.tailscale-bmc-route.plist

# Same packaging as scripts/wake-pc.nix: the script behind a fixed interpreter.
# The Command Line Tools' python3 (needed by Homebrew anyway) is new enough.
tmp=$(mktemp)
{ printf '#!/usr/bin/python3\n'; cat "$stage/scripts/wake-pc.py"; } > "$tmp"
install -o root -g wheel -m 755 "$tmp" /usr/local/bin/wake-pc
rm -f "$tmp"
/usr/local/bin/wake-pc --help > /dev/null
printf 'tailscaled, BMC route helper and wake-pc installed.\n'
