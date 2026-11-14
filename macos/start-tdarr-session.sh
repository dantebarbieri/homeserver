#!/bin/bash
set -euo pipefail

[[ "$(/usr/bin/id -u)" == 0 ]] || {
    echo "The audit-session launcher must be started by system launchd." >&2
    exit 1
}
worker_uid="$(/usr/bin/id -u _studio)"
[[ "$worker_uid" -gt 0 ]] || {
    echo "Refusing to start a privileged compute worker." >&2
    exit 1
}

# NetFS uses the audit identity, not just the effective UID. No worker-owned
# program, config or credential is read until sudo has dropped privileges.
exec /bin/launchctl asuser "$worker_uid" \
    /usr/bin/sudo -n -H -u _studio \
    /usr/bin/env -i HOME=/var/lib/studio-worker USER=_studio LOGNAME=_studio \
    TMPDIR=/var/lib/studio-worker/tmp LANG=en_US.UTF-8 \
    PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    /bin/bash /var/lib/studio-worker/start-tdarr.sh
