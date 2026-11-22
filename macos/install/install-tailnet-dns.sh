#!/bin/bash
set -euo pipefail

if [[ "$(id -u)" != 0 ]]; then
    echo "Run with sudo after installing dnsmasq with Homebrew as the admin user." >&2
    exit 1
fi

stage=$(cd "$(dirname "$0")/.." && pwd)
dnsmasq=/opt/homebrew/opt/dnsmasq/sbin/dnsmasq
label=com.danteb.tailnet-dns
config=/etc/tailnet-dns.conf
plist=/Library/LaunchDaemons/$label.plist

"$dnsmasq" --test --conf-file="$stage/tailnet-dns.conf"
plutil -lint "$stage/$label.plist"
if ! /sbin/ifconfig | grep -q 'inet 100\.94\.21\.37 '; then
    echo "No-Face's Tailscale IPv4 address is not configured; refusing installation." >&2
    exit 1
fi

backup=$(mktemp -d /var/root/tailnet-dns-backup.XXXXXX)
for file in "$config" "$plist"; do
    if [[ -e "$file" ]]; then
        cp -p "$file" "$backup/"
    fi
done
printf 'Previous configuration saved in %s\n' "$backup"

install -o root -g wheel -m 644 "$stage/tailnet-dns.conf" "$config"
install -o root -g wheel -m 644 "$stage/$label.plist" "$plist"
if launchctl print "system/$label" >/dev/null 2>&1; then
    launchctl bootout "system/$label"
fi
launchctl bootstrap system "$plist"

for attempt in {1..10}; do
    if [[ "$(/usr/bin/dig +time=1 +tries=1 +short @100.94.21.37 \
        no-face.home.arpa A)" == 100.94.21.37 ]]; then
        echo "Tailnet DNS is answering on No-Face. Tailnet DNS and route approvals are separate."
        exit 0
    fi
    sleep 1
done

echo "Tailnet DNS did not become ready; inspect /var/log/tailnet-dns.log." >&2
exit 1
