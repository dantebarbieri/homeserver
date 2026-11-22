#!/bin/bash
# Run by com.danteb.tailscale-bmc-route at boot and every minute. Keeps the
# Tailscale subnet route to the BMC working: macOS tailscaled does not SNAT
# like Linux does, so without this NAT the BMC would answer tailnet addresses
# through the router, which drops them. Idempotent; prints only on change.
set -euo pipefail
anchor=com.apple/250.danteb-tailscale-bmc
rule='nat on en0 inet from 100.64.0.0/10 to 192.168.50.50 -> (en0)'

if [[ "$(/usr/sbin/sysctl -n net.inet.ip.forwarding)" != 1 ]]; then
    /usr/sbin/sysctl -w net.inet.ip.forwarding=1
fi
# A boot-time reload of /etc/pf.conf can flush com.apple sub-anchors, so check
# the loaded rule rather than trusting an earlier run.
if ! /sbin/pfctl -a "$anchor" -s nat 2>/dev/null | grep -q '192.168.50.50'; then
    printf '%s\n' "$rule" | /sbin/pfctl -q -a "$anchor" -f -
    echo "Loaded pf anchor $anchor."
fi
if ! /sbin/pfctl -s info 2>/dev/null | grep -q '^Status: Enabled'; then
    /sbin/pfctl -q -e
    echo "Enabled pf."
fi
