#!/bin/bash
# Run with sudo from the Mac admin account after activating its worker's
# restricted public key on Calcifer. Starts only the tunnel, not Tdarr.
set -euo pipefail
umask 077
[[ "$(uname -s)" == Darwin && "$EUID" == 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]] || {
    echo "Run with sudo on the Mac from the admin account with the homeserver SSH profile." >&2
    exit 1
}
src="$(cd "$(dirname "$0")/.." && pwd)"
home=/var/lib/studio-worker
label=com.danteb.studio-transfer
cd /
if launchctl print "system/$label" >/dev/null 2>&1; then
    echo "Transfer daemon already loaded; stop it before reprovisioning." >&2
    exit 1
fi
plutil -lint "$src/$label.plist"
worker() {
    /usr/bin/sudo -n -H -u _studio /usr/bin/env -i HOME="$home" PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@"
}
worker /bin/bash -ec '
    umask 077
    cd "$HOME"
    test -f .ssh/id_ed25519_transfer
    mkdir -p .ssh logs Library/Preferences mounts/media mounts/cache tmp
'
# Open worker-controlled destinations only after dropping privileges. Rename
# from the same directory so a failed read never truncates an installed file.
put() {
    worker /bin/bash -ec '
        umask 077
        cd "$HOME"
        temp=$(mktemp "${1}.XXXXXX")
        trap '\''rm -f "$temp"'\'' EXIT
        cat > "$temp"
        test -s "$temp"
        test ! -d "$1"
        mv -f "$temp" "$1"
    ' _ "$1"
}
put .ssh/config < "$src/studio-transfer-ssh.conf"
put .ssh/known_hosts < "$src/studio-transfer-known-hosts"

# Fetch through the admin's existing, pinned SSH connection. Never hand that
# identity to the worker, nor expose the SMB credential in argv or output.
credential="$(/usr/bin/sudo -n -H -u "$SUDO_USER" /usr/bin/ssh \
    -o BatchMode=yes -o StrictHostKeyChecking=yes homeserver cat /srv/docker/data/studio-transfer/samba.env)"
[[ "$credential" =~ ^ACCOUNT_studio=[a-f0-9]{64}$ ]] || {
    echo "Invalid Samba credential file; transport not started." >&2
    exit 1
}
printf '[default]\nminauth=ntlmv2\nprotocol_vers_map=4\nsigning_required=yes\n\n[127.0.0.1]\npassword=%s\n' \
    "${credential#ACCOUNT_studio=}" | put Library/Preferences/nsmb.conf
unset credential

install -o root -g wheel -m 644 "$src/$label.plist" "/Library/LaunchDaemons/$label.plist"
launchctl bootstrap system "/Library/LaunchDaemons/$label.plist"
echo "Transfer daemon loaded. Tdarr node state unchanged."
