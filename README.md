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
and a native Tdarr node that takes the CPU x265 encoding of TV episodes over from
the server (installed, activation pending: [the offload](docker/docs/TDARR-STUDIO.md)).
See [setup and rollout boundaries](macos/README.md);
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
  startup details. Its BMC-only subnet route is `192.168.50.50/32`.
  Approve that route on the Tailscale Machines page. FileVault must be
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
Windows/macOS/phone default) reach `no-face`, `calcifer` and `dante-pc` by
name, or as `<name>.<tailnet>.ts.net`. The same name works at home: peers on
the LAN connect directly, not through a relay. calcifer and No-Face do not
accept Tailscale DNS, so use the numeric addresses from `tailscale ip -4`
there.

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

## Wake the Windows PC

The `wake-pc` command sends a Wake-on-LAN packet for DANTE-PC. It is available
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
