#!/bin/bash
# Installs or updates the Studio's native Tdarr node: launcher, session script,
# mount helper, node start script, optional Tdarr plugin modules and the
# LaunchDaemon. Run as root from a copy of macos/ (and, for the plugin modules,
# of docker/tdarr/):
#
#   sudo bash macos/install/install-tdarr-node.sh [--modules DIR] [--start|--stop] [--replace-launcher]
#
# The launcher is built and ad-hoc signed only when it is missing, because
# macOS privacy (TCC) ties its one-time Full Disk Access grant to the path and
# code hash. Never rebuild it unless the launcher source changed; if it did,
# pass --replace-launcher and repeat the grant (macos/README.md).
#
# Every input is checked and built before anything is replaced. Root writes
# only root-owned paths. Files under the worker's home are written by the
# worker itself (as_worker): the worker owns that tree, so a root install that
# followed names inside it could be redirected by a symlink the worker plants
# while the installer runs.
set -euo pipefail
umask 022
[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 ]] || {
    echo "Run this script as root on the Mac Studio." >&2
    exit 1
}

src="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home=/var/lib/studio-worker
helpers=/Library/PrivilegedHelperTools
label=com.danteb.studio-tdarr
launcher=$helpers/$label-launcher
session=$helpers/$label-session
plist=/Library/LaunchDaemons/$label.plist
module_files=(hevc-offload-v1.cjs hevc-safe-v1.cjs dv5-sidecar.cjs)
modules=
action=
replace_launcher=0
while (( $# )); do
    case "$1" in
        --modules) modules="${2:?--modules needs a directory}"; shift ;;
        --start | --stop) action="${1#--}" ;;
        --replace-launcher) replace_launcher=1 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# True while launchd still knows the job.
loaded() { /bin/launchctl print "system/$label" >/dev/null 2>&1; }

# Boots the job out and waits until launchd has really dropped it.
unload() {
    /bin/launchctl bootout "system/$label" 2>/dev/null || true
    local waited=0
    while loaded; do
        (( ++waited <= 30 )) || {
            echo "$label is still loaded 30 s after bootout." >&2
            exit 1
        }
        sleep 1
    done
}

# What the daemon leaves behind as the worker: the node, its start script and
# anything working on the mounts (Tdarr's ffmpeg and ffprobe). Whisper and
# Ollama also run as the worker, so the encoder binary alone proves nothing.
workers() {
    /usr/bin/pgrep -u _studio -f "Tdarr_Node|start-tdarr\\.sh|$home/mounts/" 2>/dev/null
}

# --stop needs neither the node nor the worker account to exist.
if [[ "$action" == stop ]]; then
    unload
    /bin/launchctl disable "system/$label"
    # The node's watchdog ends within a second of the node, unless a share
    # probe is running; start-tdarr.sh caps each probe at about 25 s.
    waited=0
    while workers >/dev/null && (( ++waited <= 60 )); do sleep 1; done
    if workers >/dev/null; then
        echo "$label is unloaded and disabled, but these _studio processes are still running:" >&2
        workers >&2
        exit 3
    fi
    echo "Stopped and disabled $label; no node or encoder processes remain."
    exit 0
fi

[[ -d "$home/tdarr" && -x "$home/tdarr/Tdarr_Node" ]] || {
    echo "The Tdarr node is not installed under $home/tdarr." >&2
    exit 1
}
[[ "$(id -u _studio)" -gt 0 ]] || {
    echo "Refusing a privileged compute worker." >&2
    exit 1
}

as_worker() {
    (cd / && /usr/bin/sudo -n -H -u _studio /usr/bin/env -i \
        HOME="$home" USER=_studio LOGNAME=_studio PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@")
}

# Runs as the worker. put <mode> <source> <destination> replaces the destination
# with one rename of a copy made inside the worker's home, then proves the result.
IFS= read -r -d '' worker_install <<'WORKER' || true
set -eu
umask 077
stage=$1
put() {
    tmp=$(/usr/bin/mktemp "$HOME/.install.XXXXXX")
    if /bin/cat "$2" >"$tmp" && /bin/chmod "$1" "$tmp" && /bin/mv -f "$tmp" "$3" \
        && [ -f "$3" ] && [ ! -L "$3" ] && /usr/bin/cmp -s "$2" "$3"; then
        return 0
    fi
    /bin/rm -f "$tmp"
    echo "Could not install $3." >&2
    return 1
}
put 755 "$stage/mount-studio-share" "$HOME/mount-studio-share"
put 755 "$stage/start-tdarr.sh" "$HOME/start-tdarr.sh"
if [ -d "$stage/modules" ]; then
    custom=$HOME/tdarr/Custom
    # An earlier installer left this directory root-owned. The worker cannot
    # write to it, but it can move it aside and make its own.
    if [ -L "$custom" ] || { [ -e "$custom" ] && { [ ! -d "$custom" ] || [ ! -O "$custom" ]; }; }; then
        aside=$custom.superseded.$(/bin/date +%Y%m%d%H%M%S)
        /bin/mv "$custom" "$aside"
        echo "Moved the previous plugin directory to $aside; delete it with sudo when convenient."
    fi
    /bin/mkdir -p -m 755 "$custom"
    for module in "$stage"/modules/*.cjs; do
        put 644 "$module" "$custom/${module##*/}"
    done
fi
WORKER

# Check every input before building or replacing anything.
for file in mount-studio-share.c studio-tdarr-launcher.c start-tdarr-session.sh start-tdarr.sh "$label.plist"; do
    [[ -s "$src/$file" ]] || {
        echo "Missing $src/$file; run this from a complete copy of macos/." >&2
        exit 1
    }
done
if [[ -n "$modules" ]]; then
    for module in "${module_files[@]}"; do
        [[ -s "$modules/$module" ]] || {
            echo "Missing $modules/$module; pass a complete copy of docker/tdarr/." >&2
            exit 1
        }
    done
fi
/usr/bin/plutil -lint "$src/$label.plist"
[[ "$(as_worker /usr/bin/id -un)" == _studio ]] || {
    echo "Cannot run commands as _studio." >&2
    exit 1
}
as_worker /bin/test -w "$home" -a -w "$home/tdarr" || {
    echo "_studio cannot write to $home and $home/tdarr." >&2
    exit 1
}

# Everything that will be installed is copied or built here first. The worker
# can read the staged files but neither list nor change this directory.
work="$(mktemp -d /private/tmp/studio-tdarr-install.XXXXXX)"
trap 'rm -rf "$work"' EXIT
chmod 711 "$work"
stage=$work/stage
mkdir -m 755 "$stage"
install -m 755 "$src/start-tdarr-session.sh" "$stage/start-tdarr-session.sh"
install -m 755 "$src/start-tdarr.sh" "$stage/start-tdarr.sh"
install -m 644 "$src/$label.plist" "$stage/$label.plist"
/bin/bash -n "$stage/start-tdarr-session.sh"
/bin/bash -n "$stage/start-tdarr.sh"
/usr/bin/clang -O2 -Wall -framework CoreFoundation -framework NetFS \
    -o "$stage/mount-studio-share" "$src/mount-studio-share.c"
if [[ -n "$modules" ]]; then
    mkdir -m 755 "$stage/modules"
    for module in "${module_files[@]}"; do
        install -m 644 "$modules/$module" "$stage/modules/$module"
    done
fi

new_launcher=0
if [[ ! -e "$launcher" || "$replace_launcher" == 1 ]]; then
    new_launcher=1
    /usr/bin/clang -O2 -Wall -o "$work/launcher" "$src/studio-tdarr-launcher.c"
    /usr/bin/codesign --force --sign - --identifier com.danteb.studio-tdarr-launcher "$work/launcher"
fi

# Install: root-owned paths as root, the worker's files as the worker.
if (( new_launcher )); then
    install -d -o root -g wheel -m 755 "$helpers"
    install -o root -g wheel -m 755 "$work/launcher" "$launcher"
    echo "Installed a new launcher; it needs the Full Disk Access grant."
fi
/usr/bin/codesign --verify --strict "$launcher"
/usr/bin/codesign -dvvv "$launcher" 2>&1 | grep -E '^(Identifier|CDHash)='

install -o root -g wheel -m 755 "$stage/start-tdarr-session.sh" "$session"
install -d -o root -g wheel -m 700 /var/log/studio-tdarr
install -o root -g wheel -m 644 "$stage/$label.plist" "$plist"
as_worker /bin/bash -c "$worker_install" _ "$stage"

grant="$(/usr/bin/sqlite3 -readonly '/Library/Application Support/com.apple.TCC/TCC.db' \
    "select auth_value from access where service='kTCCServiceSystemPolicyAllFiles' and client='$launcher'" 2>/dev/null || true)"
if [[ "$grant" != 2 ]]; then
    cat >&2 <<EOF
Full Disk Access is not granted to the launcher (TCC auth_value='${grant:-none}').
Without it every file open on the SMB mounts fails with "Operation not permitted".
In System Settings > Privacy & Security > Full Disk Access, switch on
com.danteb.studio-tdarr-launcher (it is listed once the daemon has tried to
read a share; see macos/README.md).
EOF
fi

if [[ "$action" == start ]]; then
    unload
    /bin/launchctl enable "system/$label"
    # launchd can still be tearing the old job down; bootstrap then fails with an I/O error.
    for attempt in 1 2 3; do
        /bin/launchctl bootstrap system "$plist" && break
        (( attempt < 3 )) || {
            echo "launchctl bootstrap failed three times; $label is not running." >&2
            exit 1
        }
        sleep 3
    done
    loaded || {
        echo "$label is not loaded after bootstrap." >&2
        exit 1
    }
    echo "Started $label; the node starts paused. Logs: /var/log/studio-tdarr/"
else
    echo "Installed. Start it with: sudo bash $0 --start"
fi
