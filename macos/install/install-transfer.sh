#!/bin/bash
# As run on 2026-11-13 (sudo) from ~/Services/ai-staging, since deleted. The
# staged files are in macos/. Installs the worker's restricted SSH config, the
# Samba credential (fetched from the server, never stored in git) and the
# studio-transfer tunnel.
set -euo pipefail
umask 077
[[ "$(id -u)" == 0 ]]
home=/var/lib/studio-worker
staging=/Users/dante/Services/ai-staging
install -d -o _studio -g staff -m 700 "$home/.ssh" "$home/Library" \
    "$home/Library/Preferences" "$home/mounts" "$home/mounts/media" "$home/mounts/cache"
for pair in 'studio-transfer-ssh.conf:config' 'studio-transfer-known-hosts:known_hosts'; do
    source="${pair%%:*}"
    target="${pair#*:}"
    tr -d '\r' < "$staging/$source" > "$home/.ssh/$target"
    chown _studio:staff "$home/.ssh/$target"
    chmod 600 "$home/.ssh/$target"
done
credential="$(sudo -u dante /usr/bin/ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \
    homeserver cat /srv/docker/data/studio-transfer/samba.env)"
[[ "$credential" =~ ^ACCOUNT_studio=[a-f0-9]{64}$ ]]
password="${credential#ACCOUNT_studio=}"
printf '[default]\nminauth=ntlmv2\nprotocol_vers_map=4\nsigning_required=yes\n\n[127.0.0.1]\npassword=%s\n' \
    "$password" > "$home/Library/Preferences/nsmb.conf"
unset password credential
chown _studio:staff "$home/Library/Preferences/nsmb.conf"
chmod 600 "$home/Library/Preferences/nsmb.conf"
plutil -lint "$staging/com.danteb.studio-transfer.plist"
install -o root -g wheel -m 644 "$staging/com.danteb.studio-transfer.plist" \
    /Library/LaunchDaemons/com.danteb.studio-transfer.plist
launchctl bootstrap system /Library/LaunchDaemons/com.danteb.studio-transfer.plist
printf 'Restricted SSH transport started; private SMB credential installed.\n'
