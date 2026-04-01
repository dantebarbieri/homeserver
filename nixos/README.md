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

`services.xserver.videoDrivers = [ "nvidia" ]` is set for driver registration
only — it does **not** enable X11.

## Docker Compose auto-update

A systemd timer (`docker-compose-update.timer`) runs daily at 04:00 (±5 min
jitter). The corresponding oneshot service:

1. `git pull --recurse-submodules` from `/srv/homeserver`
2. `docker compose pull && build && up -d --remove-orphans`

A deploy key is auto-generated on first activation at
`/root/.ssh/docker-compose-deploy` — add the public key to GitHub as a
read-only deploy key.

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
