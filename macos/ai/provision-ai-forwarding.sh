#!/bin/bash
# Provision an independent forward-only identity for Whisper or Ollama:
#   sudo ./provision-ai-forwarding.sh whisper|ollama <public-key-file>
# The candidate sshd configuration is validated before it is installed, and
# removed again if the live check fails, so a mistake cannot lock out SSH.
set -euo pipefail

[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 && $# == 2 ]] || {
    echo "Usage (root, on the Mac Studio): $0 whisper|ollama <public-key-file>" >&2
    exit 1
}

case "$1" in
    whisper)
        account=_bazarr; port=9000; label="Bazarr Whisper forwarding"
        keys=/etc/ssh/bazarr-forwarding-keys
        dropin_name=002-bazarr-forwarding.conf ;;
    ollama)
        account=_arrmaint; port=11434; label="Arr maintenance Ollama forwarding"
        keys=/etc/ssh/arr-maint-forwarding-keys
        dropin_name=003-arr-maint-forwarding.conf ;;
    *) echo "Expected whisper or ollama." >&2; exit 1 ;;
esac
public_key="$2"
server=192.168.50.100
dropin=/etc/ssh/sshd_config.d/$dropin_name
here="$(cd "$(dirname "$0")" && pwd)"

[[ "$(grep -c . "$public_key")" == 1 ]] || { echo "Expected one public key line." >&2; exit 1; }
read -r type key comment < "$public_key" || true
[[ "$type" == ssh-ed25519 && -n "$key" ]] || {
    echo "Expected an ssh-ed25519 public key without options." >&2
    exit 1
}
ssh-keygen -lf "$public_key" >/dev/null

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
    dscl . -create "/Users/$account" RealName "$label"
    dscl . -create "/Users/$account" Password '*'
    dscl . -create "/Users/$account" IsHidden 1
fi
case "$(dscl . -read "/Users/$account" UserShell)" in
    "UserShell: /usr/bin/false"|"UserShell: /bin/sh") ;;
    *) echo "Refusing an unexpected forwarding account shell." >&2; exit 1 ;;
esac
if id -Gn "$account" | tr ' ' '\n' | grep -Eq '^(admin|wheel)$'; then
    echo "Refusing a privileged forwarding account." >&2
    exit 1
fi

umask 022
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf 'restrict,port-forwarding,permitopen="127.0.0.1:%s",from="%s" %s %s %s\n' \
    "$port" "$server" "$type" "$key" "${comment:-arr-ai}" > "$work/keys"
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
        grep -E '^(allowtcpforwarding|permitopen|permitlisten|permittty|forcecommand|authorizedkeysfile|maxsessions) ' |
        sort
}
admin_policy="$(effective /etc/ssh/sshd_config dante)"
check() {
    /usr/sbin/sshd -t -f "$1" &&
    [[ "$(effective "$1" "$account")" == "allowtcpforwarding local
authorizedkeysfile $keys
forcecommand /usr/bin/false
maxsessions 0
permitlisten none
permitopen 127.0.0.1:$port
permittty no" ]] &&
    [[ "$(effective "$1" dante)" == "$admin_policy" ]]
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
# macOS PAM rejects /usr/bin/false even for ssh -N. Block session channels in
# sshd before assigning a PAM-accepted shell; forwarding needs no session.
dscl . -create "/Users/$account" UserShell /bin/sh
dseditgroup -o edit -a "$account" -t user com.apple.access_ssh
printf '%s can forward only to 127.0.0.1:%s from %s.\n' "$account" "$port" "$server"
