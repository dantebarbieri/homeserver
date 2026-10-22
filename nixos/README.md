# homeserver-nixos

NixOS configuration for **homeserver** — a headless home server that hosts
Docker-based services (see [homeserver-docker](https://github.com/dantebarbieri/homeserver-docker)) with a
[Homer](https://github.com/bastienwirtz/homer) dashboard at
**<https://homer.danteb.com>** (see [homeserver-homer](https://github.com/dantebarbieri/homeserver-homer)).

## Overview

| Item | Value |
|---|---|
| Hostname | `homeserver` |
| IP | `192.168.50.100/24` (static, bonded NICs) |
| OS | NixOS 25.11 (`system.stateVersion`) |
| Shell | Zsh |
| Editor | Neovim ([kickstart.nvim](https://github.com/nvim-lua/kickstart.nvim)) |
| GPU | NVIDIA RTX 2070 SUPER (headless, production driver) |
| Containers | Docker + Docker Compose (auto-updated daily at 04:00) |
| Auth | SSH key-only on port 28; `sudo-rs` (Rust) with asterisk feedback |

## Networking

- **Bond** (`bond0`): `enp66s0f0` + `enp66s0f1` in `active-backup` mode.
- **Preferred member**: `enp66s0f1`, set through networkd's `PrimarySlave`
  on `40-enp66s0f1`. The legacy `driverOptions.primary` is not translated
  by NixOS's networkd backend. Applying this setting can change the active link;
  use a maintenance window with console access available.
- **Stack**: `systemd-networkd` + `systemd-resolved` (NetworkManager disabled).
- **IPv6**: SLAAC from router (`2603:8080:1e00:1c97::/64`); stable EUI-64 GUA `2603:8080:1e00:1c97:9e6b:ff:fe45:2bc2`.
- **DNS**: `127.0.0.1` (AdGuard Home), `1.1.1.1`, `8.8.8.8`.
- Boot waits for network readiness (`systemd.network.wait-online`).

## Storage

- **Software RAID** (`mdadm`): array `/dev/md0` with a hot spare; mdadm is
  configured to call `/usr/local/bin/mdadm-ntfy` on events.
- **LVM** enabled in both the running system and the initrd.
- Filesystem tools: `dosfstools`, `xfsprogs`, `parted`.

## GPU (NVIDIA)

The RTX 2070 SUPER runs headless with `nvidiaPersistenced` to keep the GPU
initialized without X11/Wayland. The `nvidia-container-toolkit` is enabled so
Docker containers can access the GPU (used for hardware transcoding and ML
workloads like Immich and Jellyfin).

`plex-hwaccel-check.timer` exercises Plex's CUDA/NVENC path every six hours and
alerts through ntfy if Plex silently falls back to software transcoding.

`services.xserver.videoDrivers = [ "nvidia" ]` is set for driver registration
only — it does **not** enable X11.

## Docker Compose auto-update

A systemd timer (`docker-compose-update.timer`) runs daily at 04:00 (±5 min
jitter). The corresponding oneshot service:

1. Record running image digests for rollback in `/srv/docker/image-snapshots`.
2. `git pull` from `/srv/homeserver`, with automatic Git maintenance kept in
   the foreground so its temporary lock files cannot race the subsequent
   ownership repair. The pull runs as root, so `.git` and every path the pull
   changed (plus the directories containing it) are handed back to
   `danteb:docker`; otherwise a later manual `git pull` fails with
   "Permission denied".
3. Pull non-buildable images with at most four parallel Compose operations,
   rebuild local images, reconcile containers,
   recreate Homepage, and prune unused images/networks.

Failures stop the update and trigger the existing `ntfy-failure@` handler, with
two exceptions: pulled and locally built images are isolated per service. If
the combined pull is exhausted, the job pulls services one at a time; if the
combined build fails, it rebuilds services one at a time. Either way it deploys
everything else, leaves each failing service running its previous container,
and then fails so ntfy still reports it.
Combined image pulls get at most three attempts, with 60- and 120-second
delays, before the one-at-a-time fallback. Retries and the fallback mitigate
transient registry throttling (ghcr.io has rejected the large immich CUDA image
with `toomanyrequests` during the parallel pull); they cannot fix invalid
credentials, missing images, or a sustained registry outage. Git uses
`--ff-only`, and automatic
maintenance finishes before ownership repair. The entire job holds
`/run/lock/homeserver-compose.lock`; manual Compose operations do not
automatically honor that lock.

The MirkLurk wiki frontend is in Compose profile `mirklurk-release`, so this
job never starts or recreates it. `mirklurk-auto-update.timer` (04:15, ordered
after this job) builds and deploys eligible MediaWiki base-image updates for it
and alerts only on failure or a stall; see
[MirkLurk wiki](../docker/docs/MIRKLURK.md#automatic-base-image-updates).

A deploy key is auto-generated on first activation at
`/root/.ssh/docker-compose-deploy` — add the public key to GitHub as a
read-only deploy key.

### Docker socket consumers

`docker-socket-consumers.service` follows Docker starts/restarts and serially
recreates only running Homepage, Alloy, cAdvisor and VPN namespace watcher
services in project `compose`. File bind mounts can otherwise retain an obsolete
Docker socket across daemon restarts with live-restore enabled.

The helper does not start stopped/absent consumers or dependencies, pull/build
images, or prune data. Unrelated containers retain live-restore. It shares
`/run/lock/homeserver-compose.lock` with the daily updater. Recreation briefly
interrupts selected consumers and applies their checked-out Compose configuration
and local image tags. Failure invokes the existing ntfy handler.

See [Docker socket recovery](../docker/docs/DOCKER-SOCKET-RECOVERY.md) for
selection, locking, limitations and verification.

## NixOS auto-upgrade

The daily 04:30 job uses `system.autoUpgrade.operation = "boot"` and
`allowReboot = false`: it builds a generation and selects it for the next boot
without switching the running system. `allowReboot = false` alone does **not**
prevent live activation; the upstream operation defaults to `"switch"`.

Schedule regular maintenance reboots to activate staged OS/security updates.
This keeps NVIDIA userspace and the loaded kernel module on matching versions.
A manual `nixos-rebuild switch --upgrade` can still create a mismatch and is
not a substitute for rebooting after a driver update.

The RAID scrub service is not restarted when its definition changes during a
manual switch. Its existing monitor and suppression sentinel remain alive until
the kernel finishes the check; script changes take effect on the next run.
If started while a parity check is already running, the new monitor attaches to
that check without writing a second `check` request. It refuses competing RAID
actions such as recovery/reshape and fails explicitly if a new check does not
start within 30 seconds. Mismatches, unreadable/invalid results, and notification
HTTP failures are reported as failed units through the existing ntfy handler.

Do not reboot or manually interrupt a running scrub expecting its monitor to
prove full completion afterward. A transition to idle and a zero mismatch count
alone cannot distinguish a completed check from an externally canceled one.
Finish the active check before rebooting, or deliberately arrange a fresh full
check after the maintenance reboot.

## Retired terminal mail and calendar

The server no longer installs aerc, khard, khal, vdirsyncer or aerc's w3m helper.
The login calendar and `vdirsyncer-sync` service/timer have been removed.
Existing credentials, downloaded mail, contacts, calendars and sync state are
not deleted. The general-purpose `pass` tool and GPG support are retained.
`mail-config/` remains an optional portable setup, not an active NixOS integration.

## Security

- **SSH**: key-only authentication on port 28; root login disabled.
- **Privilege escalation**: `sudo-rs` (memory-safe Rust implementation) for
  the `wheel` group with `SETENV`; classic `sudo` and `doas` are disabled.
  Provides credential caching and asterisk password feedback by default.
- **Git commits** are signed with SSH keys (`gpg.format = ssh`).

## Neovim / Kickstart.nvim

All [kickstart.nvim external dependencies](https://github.com/nvim-lua/kickstart.nvim#install-external-dependencies)
are installed: `git` (via `programs.git`), `make`, `unzip`, `gcc`, `ripgrep`,
`fd`, and `tree-sitter`.

### Why `neovim` is not in `environment.systemPackages`

`programs.neovim.enable = true` already adds the **wrapped** Neovim
(`finalPackage`) to the system PATH. Listing `pkgs.neovim` again would install
the **unwrapped** copy alongside it.

- [NixOS neovim module source](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/programs/neovim.nix)
- [NixOS Wiki — Neovim](https://wiki.nixos.org/wiki/Neovim/en)

### Clipboard (SSH / headless)

No `xclip` or `xsel` is installed. Neovim 0.10+ detects SSH sessions and uses
[OSC 52 escape sequences](https://neovim.io/doc/user/provider.html#clipboard-osc52)
natively — no X11 required on the server side.

### Nerd Font

Nerd Fonts are rendered by the SSH **client's** terminal emulator, not the
server. Install a [Nerd Font](https://www.nerdfonts.com/) on your local
machine. `kickstart.nvim` already sets `vim.g.have_nerd_font = true`.

## Applying changes

```bash
sudo nixos-rebuild switch
```

## Forgejo Actions host runner

`services.forgejo-runner.instances.worldforge` runs the `worldforge-host:host`
runner for WorldForge jobs that need `nix develop`. Docker-label jobs use the
Compose runner in `docker/compose.git.yml` instead.

| Item | Value |
|------|-------|
| Unit | `forgejo-runner-worldforge.service` |
| User | static `forgejo-runner` (not `DynamicUser`; see `configuration.nix`) |
| State / `$HOME` | `/var/lib/forgejo-runner/worldforge` |
| Token file | `/var/lib/forgejo-runner-worldforge.token` (root, `0600`, raw runner token) |
| Runner UUID | `server.connections.default.uuid` in `configuration.nix` |

The UUID identifies the runner, like a username. The token is its password, and
`forgejo-runner` rejects a `TOKEN=` prefix. Labels come from `configuration.nix`;
the runner name (`homeserver-worldforge`) exists only in Forgejo.

The runner previously used the retired `services.gitea-actions-runner` module
(`gitea-runner-worldforge.service`, `/var/lib/gitea-runner/worldforge`).
`forgejo-runner-worldforge-migrate.service` runs before the runner while the old
`.runner` file exists. It writes that file's runner token to the token file,
moves the old caches to the new state directory, and removes the old
registration files. `forgejo-runner` refuses to start when a `.runner` file
coexists with configured connections. The runner keeps its Forgejo identity
without re-registration.

```bash
systemctl status forgejo-runner-worldforge
journalctl -u forgejo-runner-worldforge-migrate -u forgejo-runner-worldforge -b
```

## Local regression checks

With Python 3, Bash, Nix, and a `nixpkgs` search-path entry available:

```bash
python3 nixos/tests/test_health_cleanup.py
```

Run from the repository root. This evaluates NixOS options and exercises scrub
and update success/failure paths with mock commands; it does not contact or modify the
server, synchronize real data, or build a system closure.
