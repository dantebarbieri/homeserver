#!/bin/sh
# Forward a private container port to the Studio's loopback-only AI API.
# The Studio account can open no other destination and gets no shell.
set -eu

state=/state
port="${STUDIO_PORT:-9000}"
case "$port" in
    9000|11434) ;;
    *) echo "STUDIO_PORT must be 9000 (Whisper) or 11434 (Ollama)." >&2; exit 1 ;;
esac
for file in id_ed25519 known_hosts; do
    if [ ! -r "$state/$file" ]; then
        echo "Missing $state/$file; see macos/ai/README.md (AI transport)." >&2
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
    -L "0.0.0.0:$port:127.0.0.1:$port" \
    "${STUDIO_USER:-_bazarr}@${STUDIO_HOST:-ai-studio.home.arpa}"
