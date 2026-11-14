#!/bin/bash
# Installs or updates the Studio's native Tdarr node: launcher, session script,
# mount helper, node start script, optional Tdarr plugin modules and the
# LaunchDaemon. Run as root from a copy of macos/ (and, for the plugin modules,
# of docker/tdarr/):
#
#   sudo bash macos/install/install-tdarr-node.sh [--modules DIR] [--start|--stop]
#
# The launcher is built and ad-hoc signed only when it is missing, because
# macOS privacy (TCC) ties its one-time Full Disk Access grant to the path and
# code hash. Never rebuild it unless the launcher source changed; if it did,
# pass --replace-launcher and repeat the grant (macos/README.md).
set -euo pipefail
umask 022
[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 ]] || {
    echo "Run this script as root on the Mac Studio." >&2
    exit 1
}

src="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home=/var/lib/studio-worker
helpers=/Library/PrivilegedHelperTools
launcher=$helpers/com.danteb.studio-tdarr-launcher
session=$helpers/com.danteb.studio-tdarr-session
plist=/Library/LaunchDaemons/com.danteb.studio-tdarr.plist
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

[[ -d "$home/tdarr" && -x "$home/tdarr/Tdarr_Node" ]] || {
    echo "The Tdarr node is not installed under $home/tdarr." >&2
    exit 1
}
[[ "$(id -u _studio)" -gt 0 ]] || {
    echo "Refusing a privileged compute worker." >&2
    exit 1
}

if [[ "$action" == stop ]]; then
    /bin/launchctl bootout system/com.danteb.studio-tdarr 2>/dev/null || true
    /bin/launchctl disable system/com.danteb.studio-tdarr
    echo "Stopped and disabled com.danteb.studio-tdarr."
    exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
/usr/bin/clang -O2 -Wall -framework CoreFoundation -framework NetFS \
    -o "$work/mount-studio-share" "$src/mount-studio-share.c"

if [[ ! -e "$launcher" || "$replace_launcher" == 1 ]]; then
    /usr/bin/clang -O2 -Wall -o "$work/launcher" "$src/studio-tdarr-launcher.c"
    /usr/bin/codesign --force --sign - --identifier com.danteb.studio-tdarr-launcher "$work/launcher"
    install -d -o root -g wheel -m 755 "$helpers"
    install -o root -g wheel -m 755 "$work/launcher" "$launcher"
    echo "Installed a new launcher; it needs the Full Disk Access grant."
fi
/usr/bin/codesign --verify --strict "$launcher"
/usr/bin/codesign -dvvv "$launcher" 2>&1 | grep -E '^(Identifier|CDHash)='

install -o root -g wheel -m 755 "$src/start-tdarr-session.sh" "$session"
install -o _studio -g staff -m 755 "$work/mount-studio-share" "$home/mount-studio-share"
install -o _studio -g staff -m 755 "$src/start-tdarr.sh" "$home/start-tdarr.sh"
if [[ -n "$modules" ]]; then
    install -d -o root -g wheel -m 755 "$home/tdarr/Custom"
    for module in hevc-offload-v1.cjs hevc-safe-v1.cjs dv5-sidecar.cjs; do
        install -o root -g wheel -m 644 "$modules/$module" "$home/tdarr/Custom/$module"
    done
fi

/usr/bin/plutil -lint "$src/com.danteb.studio-tdarr.plist"
install -d -o root -g wheel -m 700 /var/log/studio-tdarr
install -o root -g wheel -m 644 "$src/com.danteb.studio-tdarr.plist" "$plist"

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
    /bin/launchctl bootout system/com.danteb.studio-tdarr 2>/dev/null || true
    /bin/launchctl enable system/com.danteb.studio-tdarr
    /bin/launchctl bootstrap system "$plist"
    echo "Started com.danteb.studio-tdarr; the node starts paused. Logs: /var/log/studio-tdarr/"
else
    echo "Installed. Start it with: sudo bash $0 --start"
fi
