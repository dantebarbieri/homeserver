#!/bin/sh
# Forward this container's port 9000 to the Studio's loopback-only Whisper API.
# The Studio account can open no other destination and gets no shell.
set -eu

state=/state
for file in id_ed25519 known_hosts; do
    if [ ! -r "$state/$file" ]; then
        echo "Missing $state/$file; see macos/ai/README.md (Bazarr transport)." >&2
        exit 1
    fi
done

exec ssh -F /dev/null -N -T \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=yes \
    -o HostKeyAlias=ai-studio \
    -o UserKnownHostsFile="$state/known_hosts" \
    -o GlobalKnownHostsFile=/dev/null \
    -o UpdateHostKeys=no \
    -o IdentitiesOnly=yes \
    -o IdentityAgent=none \
    -o IdentityFile="$state/id_ed25519" \
    -o ForwardAgent=no \
    -o ForwardX11=no \
    -L 0.0.0.0:9000:127.0.0.1:9000 \
    "${STUDIO_USER:-_bazarr}@${STUDIO_HOST:-ai-studio.home.arpa}"
