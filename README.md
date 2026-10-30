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
nixos/               NixOS system configuration (configuration.nix)
homepage/            Homepage dashboard YAML config
mail-config/         Optional legacy terminal mail/calendar config (not installed on server)
recyclarr-configs/   TRaSH Guides quality profiles for Sonarr/Radarr
production-configs/  Gitignored production config copies for debugging
```

## How It Works

**NixOS** is the declarative OS layer — it manages the Docker daemon, a daily auto-update timer, RAID/drive health monitoring, and SSH. Terminal mail/calendar tooling and its synchronization timer have been retired; existing data is preserved.

**Docker Compose** is the service orchestration layer. `docker-compose.yml` uses the `include:` directive to pull in self-contained category files (`compose.*.yml`). Each category can run independently. Services extend from shared base templates in `compose.common.yml`.

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

## Wake the Windows PC

The homeserver's `wake-pc` command sends a Wake-on-LAN packet for DANTE-PC.
After connecting to the home VPN, SSH to the homeserver in Termius and run:

```bash
wake-pc
wake-pc --wait
wake-pc --wait 60
wake-pc --help
wake-pc --mac 02:11:22:33:44:55 --broadcast 192.168.50.255 --port 9
wake-pc --mac 02:11:22:33:44:55 --wait --wait-host 192.168.50.200 --wait-port 3389
```

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
Nix-managed Python interpreter. `nixos/configuration.nix` includes that package
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
