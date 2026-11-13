#!/bin/bash
set -euo pipefail
umask 077
[[ "$(id -un)" == _studio ]] || {
    echo "Tdarr must run as the isolated _studio account." >&2
    exit 1
}
export HOME=/var/lib/studio-worker
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

for share in media cache; do
    mountpoint="$HOME/mounts/$share"
    [[ -d "$mountpoint" && ! -L "$mountpoint" ]] || {
        echo "Missing or unsafe $share mount directory." >&2
        exit 1
    }
    "$HOME/mount-studio-share" "$share"
done

export nodeName=Studio-Native
export nodeType=mapped
# Loopback endpoints only; the restricted SSH tunnel encrypts the LAN hop.
export serverURL=http://127.0.0.1:8266
export ffmpegPath=/opt/homebrew/bin/ffmpeg
# Environment-supplied path mappings must be base64-encoded JSON.
export pathTranslators
pathTranslators="$(printf %s '[{"server":"/data/media","node":"/private/var/lib/studio-worker/mounts/media"},{"server":"/temp/studio-native","node":"/private/var/lib/studio-worker/mounts/cache"}]' | base64 | tr -d '\r\n')"
export startPaused=true
export transcodecpuWorkers=1
export transcodegpuWorkers=0
export healthcheckcpuWorkers=0
export healthcheckgpuWorkers=0
export apiKey
apiKey="$(cat "$HOME/tdarr-api-key")"
[[ -n "$apiKey" ]] || {
    echo "Missing private Tdarr node API key." >&2
    exit 1
}
cd "$HOME/tdarr"
exec ./Tdarr_Node
