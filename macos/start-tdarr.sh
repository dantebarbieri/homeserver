#!/bin/bash
set -euo pipefail
umask 077
[[ "$(id -un)" == _studio ]] || {
    echo "Tdarr must run as the isolated _studio account." >&2
    exit 1
}
export HOME=/var/lib/studio-worker
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
media="$HOME/mounts/media"
cache="$HOME/mounts/cache"

# SMB can hang instead of failing, so every probe of a share is time-bounded.
bounded() { /usr/bin/perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$@"; }

# A wedged per-user NetAuthSysAgent (stuck in LsarLookupNames) blocks every
# later mount for this account. launchd respawns the agent on demand.
reset_netauth() {
    /usr/bin/pkill -KILL -u "$(/usr/bin/id -u)" -x NetAuthSysAgent || true
    /bin/sleep 3
}

mount_share() {
    local share="$1" mountpoint="$HOME/mounts/$1" attempt
    [[ -d "$mountpoint" && ! -L "$mountpoint" ]] || {
        echo "Missing or unsafe $share mount directory." >&2
        return 1
    }
    for attempt in 1 2 3; do
        "$HOME/mount-studio-share" "$share" && return 0
        echo "Mounting $share failed (attempt $attempt of 3)." >&2
        bounded 20 /sbin/umount -f "$mountpoint" 2>/dev/null || true
        reset_netauth
    done
    return 1
}

# A mount can succeed while macOS privacy (TCC) still answers "Operation not
# permitted" to every open. Prove real reads and writes before the node can
# take a job; a failed start is retried by launchd.
smoke_test() {
    local sample
    bounded 30 /bin/ls "$media" >/dev/null || {
        echo "Smoke test: cannot list the media share." >&2
        return 1
    }
    sample="$(bounded 60 /usr/bin/find "$media" -maxdepth 4 -type f -print -quit)" || sample=
    [[ -n "$sample" ]] && bounded 30 /usr/bin/head -c 16 "$sample" >/dev/null || {
        echo "Smoke test: cannot read a file on the media share." >&2
        return 1
    }
    bounded 30 /bin/bash -c '
        marker="$1/.node-smoke.$$"
        printf ok > "$marker" && [[ "$(/bin/cat "$marker")" == ok ]] && /bin/rm -f "$marker"
    ' _ "$cache" || {
        echo "Smoke test: cannot write to the cache share." >&2
        return 1
    }
}

# Three failed checks in a row (about three minutes) mean the mount died while
# the node was running; stop the node so launchd restarts it and remounts.
watchdog() {
    local node_pid="$1" failures=0
    while /bin/kill -0 "$node_pid" 2>/dev/null; do
        /bin/sleep 60
        if bounded 20 /bin/ls "$media" >/dev/null 2>&1 && bounded 20 /bin/ls "$cache" >/dev/null 2>&1; then
            failures=0
            continue
        fi
        failures=$((failures + 1))
        echo "Share health check failed ($failures of 3)." >&2
        if (( failures >= 3 )); then
            echo "Stopping the node to remount the shares." >&2
            /bin/kill -TERM "$node_pid" 2>/dev/null || true
            /bin/sleep 20
            /bin/kill -KILL "$node_pid" 2>/dev/null || true
            return 0
        fi
    done
}

mount_share media
mount_share cache
smoke_test

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
# Detached so the node never owns it; it exits once the node does.
( watchdog "$$" & ) &
# Encodes yield to the Studio's interactive and AI work.
exec /usr/bin/nice -n 10 ./Tdarr_Node
