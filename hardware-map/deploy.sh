#!/usr/bin/env bash
set -euo pipefail

[[ "$EUID" -eq 0 ]] || { echo "Run this installer with sudo." >&2; exit 1; }
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
[[ -z "$(git -C "$root" status --porcelain)" ]] || { echo "Refusing an uncommitted deployment." >&2; exit 1; }
for network in compose_proxy compose_monitoring; do
  docker network inspect "$network" >/dev/null
done

# Install only the new unit, not an entire NixOS generation. /usr/local is a
# persistent systemd search path on this host; the GC root retains its closure.
nix build --out-link /srv/server-atlas/collector-unit \
  "$root/nixos#nixosConfigurations.homeserver.config.systemd.units.\"server-atlas-collector.service\".unit"
unit="$(readlink -f /srv/server-atlas/collector-unit)/server-atlas-collector.service"
[[ -f "$unit" ]] || { echo "Collector unit was not built." >&2; exit 1; }
if [[ -e /etc/systemd/system/server-atlas-collector.service ]]; then
  echo "Collector is NixOS-managed; rebuild its declarative configuration instead of replacing it." >&2
  exit 1
fi
install -d /usr/local/lib/systemd/system/multi-user.target.wants
ln -sfn "$unit" /usr/local/lib/systemd/system/server-atlas-collector.service
ln -sfn ../server-atlas-collector.service /usr/local/lib/systemd/system/multi-user.target.wants/server-atlas-collector.service
systemctl daemon-reload
systemctl restart server-atlas-collector.service
docker compose -f "$root/hardware-map/compose.yml" build server-atlas
docker compose -f "$root/hardware-map/compose.yml" up -d --no-deps --timeout 10 --wait --wait-timeout 90 server-atlas
echo "Collector and web service installed. Configure the Prometheus scrape and admin-only Authelia/NPM route before publishing."
