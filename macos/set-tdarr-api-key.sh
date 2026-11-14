#!/bin/bash
set -euo pipefail

[[ "$EUID" == 0 ]] || {
    echo "Run with sudo to provision the isolated worker's API key." >&2
    exit 1
}
IFS= read -r -s -p "Paste the NEW Tdarr API key (input hidden): " key
printf '\n'
key="${key%$'\r'}"
[[ "$key" =~ ^tapi_[A-Za-z0-9_-]{9,}$ ]] || {
    echo "Invalid API key format; nothing was saved." >&2
    exit 1
}

# The secret travels only over stdin; the unprivileged writer refuses existing
# paths, including symlinks. No root-owned file is opened inside the worker home.
printf '%s\n' "$key" | /usr/bin/sudo -n -H -u _studio \
    /usr/bin/env -i HOME=/var/lib/studio-worker \
    /bin/bash -c 'set -euo pipefail; umask 077; set -C; /bin/cat > "$HOME/tdarr-api-key"'
unset key
echo "Stored the dedicated API key privately for _studio."
