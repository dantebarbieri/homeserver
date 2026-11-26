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
the server (active since 2026-11-22: [the offload](docker/docs/TDARR-STUDIO.md)).
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

For the [ASUS router over Tailscale](http://router.home.arpa/Main_Login.asp?redirct=false),
bookmark that exact URL. The router's `redirct=false` parameter keeps its
login page from switching to `www.asusrouter.com`. Split DNS sends
`home.arpa` lookups to no-face, which resolves them through calcifer's
AdGuard, so while calcifer is down use
`http://192.168.50.1/Main_Login.asp?redirct=false` instead.

For the [cable modem over Tailscale](https://192.168.100.1/Login.html),
bookmark that exact HTTPS URL: the modem's root page redirects to plain
HTTP.

- **calcifer:** native NixOS daemon, managed by
  [`nixos/modules/tailscale.nix`](nixos/modules/tailscale.nix); after deployment,
  run `sudo tailscale up --accept-dns=false --accept-routes=false --ssh=false`
  and complete browser login. Explicit flags preserve existing DNS and
  key-only SSH on port 28 during first enrollment.
- **no-face:** boot-time `tailscaled` plus `wake`; see
  [`macos/DECISIONS.md`](macos/DECISIONS.md) for the installed paths and
  startup details. It advertises three single-host subnet routes, each
  approved on the Tailscale Machines page: `192.168.50.50/32` (the BMC),
  `192.168.50.1/32` (the ASUS router) and `192.168.100.1/32` (the ARRIS
  SURFboard S33 cable modem). No other LAN address is routed. FileVault
  must be unlocked after a cold boot before any macOS daemon can run.
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

From a remote client on cellular or another network, with only Tailscale
connected, verify:

1. SSH to calcifer's Tailscale IP on port 28 and no-face's on port 22,
   using their normal accounts and keys.
2. RDP to Windows's Tailscale IP. Windows must be awake; Tailscale is not
   a Wake-on-LAN broadcast tunnel.
3. Open `https://192.168.50.50` through No-Face's approved route. Use the
   BMC's own credentials and expect its existing self-signed certificate.
   `ipmi.danteb.com` still depends on calcifer's NPM/Authelia and is **not**
   the recovery path.
4. Open the router and modem bookmarks above through No-Face's other two
   routes.
5. SSH to no-face and use `wake pc --wait` when the PC is intentionally
   asleep. This sends the magic packet locally on the LAN.

The modem presents its own ARRIS device certificate, which never matches
`192.168.100.1`, so every browser warns. Before accepting the warning,
check that the certificate's SHA-256 fingerprint is
`59:FE:5C:BE:68:03:7A:84:EC:E4:AA:50:0D:8D:6D:CC:4F:C9:25:13:F8:22:DB:DC:14:25:D3:1F:9B:DA:D5:87`
(checked 2026-11-26; a modem firmware update may legitimately replace it).
The modem's own password is still required. Repeated failed logins lock its
web user until the modem reboots; a reboot drops the home internet and with
it this remote path. calcifer cannot reach the modem at all (Docker's
`compose_authelia` network, `192.168.96.0/20`, contains `192.168.100.1`),
so there is no NPM or Tailscale Serve URL for it; see
[`macos/DECISIONS.md`](macos/DECISIONS.md#tailnet-lan-admin-routes-and-wake).

On Linux remote clients, enable route acceptance with
`sudo tailscale set --accept-routes=true`; Windows/macOS normally accept
routes by default. Checking these addresses from a machine already on the
home LAN does not by itself prove subnet routing works. Do not shut down
calcifer just to test it without a planned maintenance window.

## Wake machines on the LAN

[`wake`](https://github.com/dantebarbieri/wake) sends Wake-on-LAN magic
packets to the machines in the house. It is installed on calcifer (from the
flake input in `nixos/flake.nix`, via `nixos/modules/users.nix`), No-Face and
the Windows PC, and always skips the machine it runs on. Over Tailscale, SSH
to No-Face to wake the PC even while calcifer is down.

```bash
wake pc            # send the packet
wake pc --wait     # ...and wait (up to 120 s) until RDP answers
wake all -w 60     # every other machine
wake status        # which machines are up
wake list          # presets: pc, no-face, calcifer
```

- **pc** (`74:56:3C:B4:F5:4E`, RDP on `192.168.50.180:3389`): its **Ethernet
  cable must be connected**; the wired adapter can't receive a magic packet
  while unplugged, even if RDP works over Wi-Fi.
- **no-face** wakes only from sleep (Apple Silicon can't be woken from
  shutdown), and it is set never to sleep, so this is rarely needed.
- **calcifer** gets the packet on both bonded NICs' permanent MACs. The
  `wake-on-lan` unit in `nixos/modules/networking.nix` arms WoL on them at
  boot; check it with `systemctl status wake-on-lan`, since X550 support
  depends on the card. If `WAKE_IPMI_USER` and `IPMI_PASSWORD` are set (in
  `~/.zshrc.local`, never in the repo) and `ipmitool` is installed, `wake
  calcifer` also asks the BMC for `chassis power on`.

`wake` checks the machine's port first and skips one that already answers
(`--force` sends anyway). No router or firewall changes are needed: packets go
to the LAN broadcast `192.168.50.255:9`. Presets, installers and the release
process are in the [wake README](https://github.com/dantebarbieri/wake#readme);
the macOS and Windows copies update themselves daily, calcifer's with the
flake lock.

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
