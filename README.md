# homeserver

Monorepo for my NixOS-based home server infrastructure. 50+ Docker containers, NVIDIA RTX 2070 SUPER for transcoding/ML, ~66TB RAID6 XFS storage, reverse-proxied via [Nginx Proxy Manager](https://nginxproxymanager.com/) with [Authelia](https://www.authelia.com/) SSO.

## Services

| Category | Services |
|----------|----------|
| **Media** | Plex, Jellyfin, Komga, Komf, Suwayomi, Calibre-web, Audiobookshelf, Storyteller, BookBridge |
| **Starr** | Radarr, Sonarr, Lidarr, Bazarr, Prowlarr, Jellyseerr, Aurral, Tdarr, Recyclarr |
| **Downloads** | qBittorrent (via Gluetun VPN), SABnzbd, FlareSolverr |
| **Photos** | Immich |
| **Cloud** | Nextcloud |
| **Chat** | Matrix (Synapse + Element + LiveKit) |
| **Auth** | Authelia + LDAP |
| **Utilities** | Vaultwarden, Syncthing, ntfy, SearXNG |
| **Networking** | Nginx Proxy Manager, ddclient, Endlessh |
| **Gaming** | RomM, Minecraft, Satisfactory |
| **Dashboards** | Homepage, DashDot |

## Repository Layout

```
docker/              Docker Compose orchestration (18 category files)
nixos/               NixOS system configuration (flake + modules + Home Manager)
macos/               Isolated native Mac Studio compute and private transport
homepage/            Homepage dashboard YAML config
mail-config/         Optional legacy terminal mail/calendar config (not installed on server)
recyclarr-configs/   TRaSH Guides quality profiles for Sonarr/Radarr
production-configs/  Gitignored production config copies for debugging
```

## How It Works

**NixOS** is the declarative OS layer — it manages the Docker daemon, a daily auto-update timer, RAID/drive health monitoring, and SSH. Terminal mail/calendar tooling and its synchronization timer have been retired; existing data is preserved.

**Docker Compose** is the service orchestration layer. `docker-compose.yml` uses the `include:` directive to pull in self-contained category files (`compose.*.yml`). Each category can run independently. Services extend from shared base templates in `compose.common.yml`.

**Mac Studio** is an isolated compute companion for native speech, advisory models,
and a native CPU/x265 Tdarr node that is currently disabled. See [setup and rollout boundaries](macos/README.md);
working transport is not production media or subtitle cutover approval. Its
[intents and decisions](macos/DECISIONS.md) record what Dante wants, what an
agent chose and may be replaced, and where every piece lives.

**Daily auto-update** (04:00): a NixOS systemd timer pulls this repo and runs `docker compose pull && build && up -d`.

## Quick Start

```bash
# Clone
git clone git@github.com:dantebarbieri/homeserver.git
z homeserver

# Configure environment (see sample.env for all variables)
cp docker/sample.env docker/.env
# Edit docker/.env with your paths, credentials, and API keys

# Start everything
z docker
docker compose up -d

# Start a single service using the main index (preserves shared networks)
docker compose up -d plex

# Validate config
docker compose config
```

See [`CLAUDE.md`](CLAUDE.md) for detailed architecture documentation.

## Tailscale remote access

Hosted Tailscale replaces the server-as-VPN-gateway dependency: install and
authenticate a client on **calcifer**, **no-face**, **Windows**, and each
remote phone/laptop, all in the same tailnet. It is split-tunnel access,
not an exit node: ordinary internet traffic stays on the client's network.
Keep wg-easy running as a fallback until the off-LAN checks below pass.

- **calcifer:** native NixOS daemon, managed by
  [`nixos/modules/tailscale.nix`](nixos/modules/tailscale.nix); after deployment,
  run `sudo tailscale up --accept-dns=false --accept-routes=false --ssh=false`
  and complete browser login. Explicit flags preserve existing DNS and
  key-only SSH on port 28 during first enrollment.
- **no-face:** boot-time `tailscaled` plus `wake-pc`; see
  [`macos/DECISIONS.md`](macos/DECISIONS.md) for the installed paths and
  startup details. Its approved management routes are `192.168.50.1/32`
  (router), `192.168.50.50/32` (BMC), and `192.168.100.1/32` (modem).
  Approve these routes on the Tailscale Machines page. FileVault must be
  unlocked after a cold boot before any macOS daemon can run.
- **Windows:** install the official `Tailscale.Tailscale` WinGet package,
  sign in, then run `tailscale set --unattended=true`. The automatic
  Tailscale service must stay running when the Windows user signs out so
  RDP is available at the login screen. Keep Windows authentication and its
  RDP firewall rules; do not expose port 3389 on the internet.

In the hosted admin console, disable key expiry for trusted infrastructure
nodes that must remain reachable unattended (revoke lost devices promptly).
Restrict tailnet access to your administrator identity/devices. Do not make
calcifer's AdGuard the tailnet's sole global DNS server: recovery should
work without it. MagicDNS is on, so clients that accept Tailscale DNS (the
Windows/macOS/phone default) reach `no-face`, `calcifer` and `totoro` by
name, or as `<name>.<tailnet>.ts.net`. The same name works at home: peers on
the LAN connect directly, not through a relay. calcifer and No-Face do not
accept Tailscale DNS, so use the numeric addresses from `tailscale ip -4`
there.

Use the [unified `home.arpa` names](#unified-device-dns) in saved connection
profiles instead of maintaining separate LAN and MagicDNS profiles.

From a remote client on cellular or another network, **with wg-easy off on
that client**, verify:

1. SSH to calcifer's Tailscale IP on port 28 and no-face's on port 22,
   using their normal accounts and keys.
2. RDP to Windows's Tailscale IP. Windows must be awake; Tailscale is not
   a Wake-on-LAN broadcast tunnel.
3. Open `https://192.168.50.50` through No-Face's approved route. Use the
   BMC's own credentials and expect its existing self-signed certificate.
   `ipmi.danteb.com` still depends on calcifer's NPM/Authelia and is **not**
   the recovery path.
4. SSH to no-face and use `wake-pc --wait` when the PC is intentionally
   asleep. This sends the magic packet locally on the LAN.

On Linux remote clients, enable route acceptance with
`sudo tailscale set --accept-routes=true`; Windows/macOS normally accept
routes by default. Checking the BMC from a machine already on the home LAN
does not by itself prove subnet routing works. Do not shut down calcifer
just to test it without a planned maintenance window.

### Unified device DNS

The same fully qualified name works in RDP, VNC, SSH and browsers:

| Name | LAN answer, with Tailscale off | Tailscale answer |
|---|---|---|
| `calcifer.home.arpa` | `192.168.50.100` | `100.104.46.115` |
| `no-face.home.arpa` | `192.168.50.80` | `100.94.21.37` |
| `totoro.home.arpa` | `192.168.50.190` (Wi-Fi; see wired transition below) | `100.113.62.81` |
| `okkoto.home.arpa` | **Pending a home DHCP reservation** | `100.117.244.102` |
| `router.home.arpa` | `192.168.50.1` | Same address, routed through No-Face |
| `modem.home.arpa` | `192.168.100.1` | Same address, routed through No-Face |
| `bmc.home.arpa` | `192.168.50.50` | Same address, routed through No-Face |

**LAN view:** AdGuard's DNS rewrites hold the LAN addresses. The existing
`homeserver.home.arpa` and `ai-studio.home.arpa` aliases remain. Clients must
use a resolver that knows these records: a public DNS "fallback" such as
`1.1.1.1` can answer first and return NXDOMAIN. Totoro's Wi-Fi and Ethernet
now use only AdGuard for IPv4 DNS; its advertised IPv6 DNS is also AdGuard.
No-Face keeps its `/etc/resolver/home.arpa` override. Other LAN clients that
receive public fallback DNS from the router may still need that corrected.
**Router-wide DNS changes are deferred to a maintenance window:** ASUS
settings changes can reboot the router.

**Tailnet view:** No-Face runs a separate, non-recursive dnsmasq instance from
[`macos/tailnet-dns.conf`](macos/tailnet-dns.conf). It listens only on
`100.94.21.37:53` (UDP and TCP), drops privileges to `nobody`, and serves
`home.arpa` without depending on calcifer, AdGuard or NPM. The
`com.danteb.tailnet-dns` LaunchDaemon restarts it if the Tailscale interface
is not ready at boot. FileVault still has to be unlocked first.

In **Tailscale > DNS**, the custom nameserver is `100.94.21.37`, with
**Restrict to domain: `home.arpa`**. It is not a global nameserver; leave
**Override DNS servers** off. Client devices must accept Tailscale DNS.
calcifer and No-Face deliberately retain `--accept-dns=false` and their LAN
view so production services and LAN-restricted SSH keys keep working.
If a node is removed and re-enrolled with another Tailscale address, update
the dnsmasq records before relying on its custom name.

The Windows SSH aliases now use `calcifer.home.arpa` (port 28) and
`no-face.home.arpa` (port 22), preserving the existing pinned host identities;
there is no longer an SSH-specific Tailscale/Bonjour switch. The prior config
is at `~/.ssh/config.before-unified-dns-20261122`. Use `totoro.home.arpa` in
the MacBook's RDP profile and `no-face.home.arpa` for Screen Sharing/VNC
(port 5900); those saved profiles are edited on their originating device.

**Totoro's wired transition:** both reservations are confirmed: Ethernet is
the primary at `.180`, Wi-Fi is `.190`. While Ethernet is disconnected,
AdGuard deliberately answers `.190`. Once Ethernet is connected and RDP on
`.180` is reachable, change only the `totoro.home.arpa` AdGuard rewrite to
`192.168.50.180`; do not publish both addresses while one adapter is offline.
The name in saved profiles and the tailnet DNS record do not change.
Windows's computer rename to `Totoro` is staged for the next planned restart;
the Tailscale node is already `totoro`. No reboot was performed.

**Okkoto:** the MacBook Pro was renamed locally by Dante. Its tailnet DNS alias
works even while the Tailscale app still displays the old
`dantes-macbook-pro` machine name. It has no home DHCP reservation yet, so no
LAN record has been invented. Add that record after reserving an address
when it returns home. Naming does not enable inbound SSH or Screen Sharing.

Management pages are [the router](http://router.home.arpa/),
[the modem](https://modem.home.arpa/) and
[the direct BMC recovery page](https://bmc.home.arpa/).
They use their existing logins; HTTPS appliances retain their existing
certificate warnings. The modem's redirects end at its HTTPS login page.
These are private routes, not WAN administration or public reverse proxies.
No router/modem settings were changed. Preserve the three `/32` routes when
updating No-Face's `--advertise-routes` setting (the flag replaces the list).
Keep numeric management addresses and MagicDNS as recovery fallbacks if the
private DNS service is unavailable.

## Wake the Windows PC

The `wake-pc` command sends a Wake-on-LAN packet for Totoro (formerly DANTE-PC). It is available
on the homeserver and on No-Face. After connecting to Tailscale, SSH to
No-Face's Tailscale IP in Termius to wake the PC even when calcifer is down.
The existing homeserver command also works while that server is available:

```bash
wake-pc
wake-pc --wait
wake-pc --wait 60
wake-pc --help
wake-pc --mac 02:11:22:33:44:55 --broadcast 192.168.50.255 --port 9
wake-pc --mac 02:11:22:33:44:55 --wait --wait-host 192.168.50.200 --wait-port 3389
```

The PC's **Ethernet cable must be connected**: its wired adapter cannot
receive a magic packet while unplugged, even if RDP currently works over
Wi-Fi. The `.180` wait target below is the wired LAN address, not the
Wi-Fi lease. From No-Face (or another enrolled host), use
`wake-pc --wait --wait-host 100.113.62.81` to wait for the PC's stable
Tailscale address instead; this changes only the readiness check, not
which adapter receives the wake packet.

With no arguments it sends one standard 102-byte UDP magic packet for Ethernet
MAC `74:56:3C:B4:F5:4E` to LAN broadcast `192.168.50.255:9`. `--mac` identifies
the device; `--broadcast` selects the LAN broadcast destination. A DHCP IP
change does not change the Ethernet MAC, so the PC's current IP is not needed.
There is no `--ip` option, hostname lookup, or ARP discovery.

Without `--wait`, success means **packet sent**, not verified readiness.
`--wait [SECONDS]` waits up to 120 seconds by default for a TCP connection to
RDP at `192.168.50.180:3389`. This means the RDP port is reachable, not that
Windows login has completed or that this command caused a wake: the PC may
already have been online. A timeout means RDP was not reachable, not proof of
a power failure. Both wake senders have successfully woken this PC in a
user-controlled test; the exact tested power state was not recorded.

`--wait-host` and `--wait-port` customize only the verification endpoint and
require `--wait`; changing `--mac` does not change that endpoint automatically.
Unlike the Ethernet MAC, the verification IP must be updated if DHCP changes it.
Numeric IPv4 targets avoid stale hostname lookup and bound connection attempts
to the overall timeout; no ping or ARP discovery is used. No router port
forwarding, exposed UDP port, or network changes are needed: the homeserver
sends locally on the LAN.

The source is `scripts/wake-pc.py`; `scripts/wake-pc.nix` packages it with a
Nix-managed Python interpreter. `nixos/modules/users.nix` includes that package
in `users.users.danteb.packages`, so it is installed declaratively for `danteb`
at `/etc/profiles/per-user/danteb/bin/wake-pc` on a system rebuild:

```bash
sudo nixos-rebuild switch
command -v wake-pc
```

No pip packages or shell PATH edits are needed. Rebuilds capture the checked-out
source, and the command is restored from configuration rather than depending on
an imperative user-profile installation. If migrating from the earlier manual
installation, verify the declarative command works before running
`nix profile remove wake-pc`; otherwise the older `~/.nix-profile/bin` copy
can shadow declarative updates. Exit codes are `0`
for a successful send/help (or RDP reachability with `--wait`), `1` for send,
verification errors or timeout, `2` for invalid arguments, and `130` for Ctrl-C.
Run non-disruptive unit and loopback-packet checks locally with
`uv run --no-project python -B -m unittest discover -s scripts/tests -p 'test_wake_pc.py'`.

## Starr installer hosting

For a fresh Linux server without NixOS, use the independent public
[Starr installer source](https://github.com/dantebarbieri/starr-installer) and
[installer documentation](https://github.com/dantebarbieri/starr-installer#readme).
The [hosted guide and command builder](https://starr.danteb.com) is live and
serves `/i`, `/install.sh` and `/install.py`.

This repository only hosts the installer using
`ghcr.io/dantebarbieri/starr-installer:latest`. Required checks and gated image
publication belong to the installer repository. The image is publicly pullable,
and the existing homeserver updater pulls new published images. The image bundles its
source and public profile snapshot at `/source` (`SOURCE_ROOT`); the authoritative
Recyclarr profiles remain here in `recyclarr-configs/`. There are no runtime
source/profile mounts, Docker socket access, or host ports. The image's own
entrypoint runs as UID/GID 65534 with a read-only filesystem.

For subsequent deployments, use the main Compose entry point and retain the
production project name (`compose`), so NPM and `starr` share the existing proxy
network. Do not deploy the websites category file independently:

```bash
z /srv/homeserver/docker
docker compose --project-name compose pull starr
docker compose --project-name compose up -d --no-deps --wait starr
```

Nginx Proxy Manager routes `starr.danteb.com` to HTTP upstream `starr:8080`
using the existing wildcard TLS certificate, Force SSL and Block Common Exploits.
Keep `PUBLIC_URL` set to
`https://starr.danteb.com`. Do not add Authelia or a login access list: the guide
and installer downloads are intentionally public, read-only resources with no
accounts or privileged API. Health checks use `/healthz`; Homepage's Development
group includes Starr Installer and monitors that URL and the `starr` container.
No NixOS, router or firewall changes are
needed because NPM provides the existing HTTPS ingress.

For music, see [Lidarr + Plexamp](docker/docs/MUSIC.md): a shared FLAC library,
lossless download stores, and iPhone/Windows/macOS playback using the existing
Plex server.
