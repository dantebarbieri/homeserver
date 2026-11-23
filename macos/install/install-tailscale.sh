#!/bin/bash
# As run on No-Face on 2026-11-21 (sudo). Installs the open-source tailscaled
# as a boot-time LaunchDaemon (the only macOS variant that runs before login).
# Logging in to the tailnet is a separate, interactive step: see
# macos/DECISIONS.md. The wake command (formerly wake-pc, installed here) now
# has its own installer: https://github.com/dantebarbieri/wake
set -euo pipefail
[[ "$(id -u)" == 0 ]]
admin=dantebarbieri

(cd /tmp && sudo -H -u "$admin" /opt/homebrew/bin/brew install tailscale)
# Copies the binary to /usr/local/bin/tailscaled; brew upgrade does not touch
# that copy, so rerun this after upgrading.
/opt/homebrew/bin/tailscaled install-system-daemon
printf 'tailscaled installed.\n'
# Then, once: sudo tailscale up --hostname=no-face \
#   --advertise-routes=192.168.50.50/32 --accept-routes=false --accept-dns=false
