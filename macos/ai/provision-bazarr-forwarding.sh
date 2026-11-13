#!/bin/bash
# Create or update the forward-only SSH account Bazarr uses to reach the
# Studio's loopback Whisper API. Run as root on the Studio from this directory:
#   sudo ./provision-bazarr-forwarding.sh <bazarr-public-key-file>
# The candidate sshd configuration is validated before it is installed, and
# removed again if the live check fails, so a mistake cannot lock out SSH.
set -euo pipefail

[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 && $# == 1 ]] || {
    echo "Usage (root, on the Mac Studio): $0 <bazarr-public-key-file>" >&2
    exit 1
}

account=_bazarr
server=192.168.50.100
keys=/etc/ssh/bazarr-forwarding-keys
dropin_name=002-bazarr-forwarding.conf
dropin=/etc/ssh/sshd_config.d/$dropin_name
here="$(cd "$(dirname "$0")" && pwd)"

[[ "$(grep -c . "$1")" == 1 ]] || { echo "Expected one public key line." >&2; exit 1; }
read -r type key comment < "$1" || true
[[ "$type" == ssh-ed25519 && -n "$key" ]] || {
    echo "Expected an ssh-ed25519 public key without options." >&2
    exit 1
}
ssh-keygen -lf "$1" >/dev/null

users="$(dscl . -list /Users UniqueID)"
if ! awk '{print $1}' <<<"$users" | grep -qx "$account"; then
    uid=498
    while awk '{print $2}' <<<"$users" | grep -qx "$uid"; do
        uid=$((uid - 1))
        (( uid >= 450 )) || { echo "No unused service UID." >&2; exit 1; }
    done
    dscl . -create "/Users/$account"
    dscl . -create "/Users/$account" UniqueID "$uid"
    dscl . -create "/Users/$account" PrimaryGroupID -2
    dscl . -create "/Users/$account" NFSHomeDirectory /var/empty
    dscl . -create "/Users/$account" UserShell /usr/bin/false
    dscl . -create "/Users/$account" RealName "Bazarr Whisper forwarding"
    dscl . -create "/Users/$account" Password '*'
    dscl . -create "/Users/$account" IsHidden 1
fi
[[ "$(dscl . -read "/Users/$account" UserShell)" == "UserShell: /usr/bin/false" ]]
if id -Gn "$account" | tr ' ' '\n' | grep -Eq '^(admin|wheel)$'; then
    echo "Refusing a privileged forwarding account." >&2
    exit 1
fi

umask 022
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf 'restrict,port-forwarding,permitopen="127.0.0.1:9000",from="%s" %s %s %s\n' \
    "$server" "$type" "$key" "${comment:-bazarr-whisper}" > "$work/keys"
mkdir "$work/sshd_config.d"
cp -p /etc/ssh/sshd_config.d/* "$work/sshd_config.d/"
cp "$here/$dropin_name" "$work/sshd_config.d/"
sed "s|^Include /etc/ssh/sshd_config.d/\*$|Include $work/sshd_config.d/*|" \
    /etc/ssh/sshd_config > "$work/sshd_config"
grep -qx "Include $work/sshd_config.d/\*" "$work/sshd_config"

effective() {
    /usr/sbin/sshd -T -f "$1" -C "user=$2,host=homeserver,addr=$server" |
        # OpenSSH 10.5 prints canonical-case keywords; older releases use lowercase.
        awk '{ $1 = tolower($1); print }' |
        grep -E '^(allowtcpforwarding|permitopen|permitlisten|permittty|forcecommand|authorizedkeysfile) ' |
        sort
}
check() {
    /usr/sbin/sshd -t -f "$1" &&
    [[ "$(effective "$1" "$account")" == "allowtcpforwarding local
authorizedkeysfile $keys
forcecommand /usr/bin/false
permitlisten none
permitopen 127.0.0.1:9000
permittty no" ]] &&
    [[ "$(effective "$1" dante)" == "$(effective /etc/ssh/sshd_config dante)" ]]
}
check "$work/sshd_config" || {
    echo "Candidate sshd policy is invalid or affects other accounts:" >&2
    effective "$work/sshd_config" "$account" >&2
    exit 1
}

install -o root -g wheel -m 644 "$work/keys" "$keys"
install -o root -g wheel -m 644 "$here/$dropin_name" "$dropin"
check /etc/ssh/sshd_config || {
    rm -f "$dropin"
    echo "Live sshd check failed; removed $dropin." >&2
    exit 1
}
dseditgroup -o edit -a "$account" -t user com.apple.access_ssh
printf '%s can forward only to 127.0.0.1:9000 from %s.\n' "$account" "$server"
