#!/bin/bash
set -euo pipefail

[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 ]] || {
    echo "Run this script as root on the Mac Studio." >&2
    exit 1
}

worker=_studio
home=/var/lib/studio-worker
users="$(dscl . -list /Users UniqueID)"
if ! awk '{print $1}' <<<"$users" | grep -qx "$worker"; then
    worker_uid=499
    while awk '{print $2}' <<<"$users" | grep -qx "$worker_uid"; do
        worker_uid=$((worker_uid - 1))
        if (( worker_uid < 450 )); then
            echo "No unused service UID in the reserved setup range." >&2
            exit 1
        fi
    done
    dscl . -create "/Users/$worker"
    dscl . -create "/Users/$worker" UniqueID "$worker_uid"
    dscl . -create "/Users/$worker" PrimaryGroupID 20
    dscl . -create "/Users/$worker" NFSHomeDirectory "$home"
    dscl . -create "/Users/$worker" UserShell /usr/bin/false
    dscl . -create "/Users/$worker" RealName "Studio compute worker"
    dscl . -create "/Users/$worker" Password '*'
    dscl . -create "/Users/$worker" IsHidden 1
fi

[[ "$(dscl . -read "/Users/$worker" NFSHomeDirectory)" == "NFSHomeDirectory: $home" ]]
[[ "$(dscl . -read "/Users/$worker" UserShell)" == "UserShell: /usr/bin/false" ]]
[[ "$(id -u "$worker")" -gt 0 ]] || {
    echo "Refusing a privileged compute worker." >&2
    exit 1
}
if id -Gn "$worker" | tr ' ' '\n' | grep -Eq '^(admin|wheel|com\.apple\.access_ssh)$'; then
    echo "Refusing to use a privileged or SSH-enabled worker account." >&2
    exit 1
fi

[[ ! -L "$home" ]] || {
    echo "Refusing a symlinked worker home." >&2
    exit 1
}
if [[ ! -e "$home" ]]; then
    install -d -o "$worker" -g staff -m 700 "$home"
fi
[[ -d "$home" && "$(stat -f '%Su %Sp' "$home")" == "$worker drwx------" ]] || {
    echo "Expected an existing private, worker-owned home." >&2
    exit 1
}
# Once the worker owns its home, only that identity may create/change children.
sudo -n -H -u "$worker" /usr/bin/env -i HOME="$home" /bin/bash -c '
    set -euo pipefail
    umask 077
    for directory in "$HOME/.ssh" "$HOME/logs"; do
        [[ ! -L "$directory" ]] || {
            echo "Refusing a symlinked worker directory." >&2
            exit 1
        }
        /bin/mkdir -p "$directory"
        /bin/chmod 700 "$directory"
    done
'
key="$home/.ssh/id_ed25519_transfer"
if [[ ! -e "$key" ]]; then
    sudo -u "$worker" /usr/bin/ssh-keygen -q -t ed25519 -N '' \
        -C studio-transfer@ai-studio -f "$key"
fi
[[ -f "$key" && ! -L "$key" && -f "$key.pub" && ! -L "$key.pub" ]]
[[ "$(stat -f '%Su %Sp' "$key")" == "$worker -rw-------" ]]
/usr/bin/ssh-keygen -lf "$key.pub"
id "$worker"
