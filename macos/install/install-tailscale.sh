#!/bin/bash
# As run on No-Face on 2026-11-21 (sudo, from a staged copy of this repo's
# scripts/ directory). Installs the open-source tailscaled as a boot-time
# LaunchDaemon (the only macOS variant that runs before login) and the wake-pc
# command. Logging in to the tailnet is a separate, interactive step: see
# macos/DECISIONS.md.
set -euo pipefail
[[ "$(id -u)" == 0 ]]
admin=dantebarbieri
stage=$(cd "$(dirname "$0")/../.." && pwd)

(cd /tmp && sudo -H -u "$admin" /opt/homebrew/bin/brew install tailscale)
# Copies the binary to /usr/local/bin/tailscaled; brew upgrade does not touch
# that copy, so rerun this after upgrading.
/opt/homebrew/bin/tailscaled install-system-daemon

# Same packaging as scripts/wake-pc.nix: the script behind a fixed interpreter.
# The Command Line Tools' python3 (needed by Homebrew anyway) is new enough.
tmp=$(mktemp)
{ printf '#!/usr/bin/python3\n'; cat "$stage/scripts/wake-pc.py"; } > "$tmp"
install -o root -g wheel -m 755 "$tmp" /usr/local/bin/wake-pc
rm -f "$tmp"
/usr/local/bin/wake-pc --help > /dev/null
printf 'tailscaled and wake-pc installed.\n'
# Then, once: sudo tailscale up --hostname=no-face \
#   --advertise-routes=192.168.50.50/32 --accept-routes=false --accept-dns=false
