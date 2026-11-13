# Mac Studio compute companion

The Studio runs native speech inference, an advisory local model, and a
**paused-by-default CPU/x265 Tdarr node**. Colima is a separate, limited Docker
environment. This setup does not move production Bazarr or authorize Tdarr to
replace original media.

See [speech setup](ai/README.md), [model comparisons and limitations](ai/SPEECH.md),
and [Tdarr's storage-authoritative flow](../docker/docs/TDARR.md).

## Identities and private transport

| Component | Identity / boundary |
|---|---|
| Native speech, Ollama, Tdarr, SSH transport | `_studio`, private `/var/lib/studio-worker` home, no admin/wheel/SSH-login access |
| Mac administrative SSH and Colima | `dante`; never lend this account's private key or Docker socket to `_studio` |
| Linux SSH transport | `studio-tunnel`, nologin, dedicated key, no shell/PTY/SFTP, reverse/agent/Unix-socket forwarding |
| Linux SMB account | `studio`; original media read-only, only the dedicated native job cache writable |
| Linux fixed TCP relays | UID/GID 65534, read-only root, no capabilities, no-new-privileges, no mounts or credentials |

`provision-worker.sh` creates or checks the isolated Mac account and generates
its transport key locally. `001-studio-worker.conf` denies incoming SSH to that
account. `allow-worker-tools.sh` grants only runtime read/execute access to the
installed Homebrew tools and their dependencies; rerun it after relevant brew
upgrades. Do not solve package permission errors by adding the worker to admin
or granting it write access to Homebrew.

The pinned-host SSH configuration and `com.danteb.studio-transfer.plist` provide:

| Mac loopback listener | Linux loopback destination | Fixed backend |
|---|---|---|
| `127.0.0.1:1445` | `127.0.0.1:1445` | `studio-media-share:445` |
| `127.0.0.1:8266` | `127.0.0.1:8266` | `tdarr:8266` |

Both `nixos/modules/ssh.nix` and the key options in `users.nix` allow exactly
those two destinations. The nondefault `/etc/ssh/studio-transfer-keys` must
remain paired with the restricted Match block: placing this key in an ordinary
authorized-keys file would defeat that fail-closed pairing.

The relays in `docker/compose.studio.yml` publish **only host loopback**. SMB's
backend network is internal; its listener network contains only the SMB relay.
The Tdarr relay uses the existing `starr` network without restarting Tdarr.
No new NPM proxy, LAN listener, router rule or host firewall opening is needed.
SSH encrypts the inter-host traffic. The same-host relay/backend traffic is
not encrypted; SMB requires signing and its own credentials, and Tdarr still
requires its dedicated API key. Server-local processes can reach the loopback
relays, so application authentication must never be disabled.

The existing `https://tdarr.danteb.com` proxy serves web port **8265**. It is
not the node socket: using it for the native node produces `Invalid namespace`.
The native node uses `http://127.0.0.1:8266` **inside the SSH tunnel**, not raw
HTTP across the LAN.

## Headless mounts and startup

Use the canonical mapped paths:

| Linux Tdarr path | Mac path |
|---|---|
| `/data/media` | `/private/var/lib/studio-worker/mounts/media` |
| `/temp/studio-native` | `/private/var/lib/studio-worker/mounts/cache` |

`/var` is a macOS symlink. NetFS mounting and strict Tdarr path validation need
`/private/var` for these mapped paths. The fixed module require path under
`/var/lib/studio-worker/tdarr/Custom` is intentionally unchanged.

Build `mount-studio-share.c` on the Mac:

```sh
clang -Wall -Wextra -Werror -O2 \
  -framework CoreFoundation -framework NetFS \
  mount-studio-share.c -o mount-studio-share
```

Install the binary as `_studio` mode 0700 in its private home. Create private
`mounts/media`, `mounts/cache`, `tmp` and `Library/Preferences` directories.
The helper reads a worker-owned mode-0600 `Library/Preferences/nsmb.conf`
containing one `password=` entry with the 64-hex SMB password. Transfer the
credential privately; never put it in this repository, command arguments,
environment variables, or logs. Current macOS `mount_smbfs -N` does not consume
that password setting; this helper passes it directly to the public NetFS API.
It verifies the exact source, canonical mountpoint, mount owner, nosuid/nodev
and read-only status.

NetAuthSysAgent uses the security audit identity, not just effective UID.
`sudo -u _studio` alone was insufficient, as was a worker LaunchDaemon with
`SessionCreate=true`. The root launcher selects the worker audit context with
`launchctl asuser`, then **also drops credentials with sudo** before reading
worker-owned code or secrets. `launchctl asuser` alone does not drop privileges.

Required installation ownership:

| Path | Owner / mode |
|---|---|
| `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-session` (from `start-tdarr-session.sh`) | root:wheel 0755 |
| `/Library/PrivilegedHelperTools` and protected ancestor directories | root-owned, no worker write access or replaceable links/ACLs |
| `/Library/LaunchDaemons/com.danteb.studio-tdarr.plist` | root:wheel 0644 |
| `/var/log/studio-tdarr` | root:wheel 0700; only regular root-owned log files |
| Worker home and `start-tdarr.sh` | `_studio`, 0700 |
| Worker `tdarr-api-key` and SMB credential file | `_studio`, 0600 |

Never put root-executed launcher code or root-opened log paths in the
worker-writable home. Copy/extract the native ARM64 bundle **as the worker**,
not with a recursive root chown of a worker-writable tree. Its executable is
`/var/lib/studio-worker/tdarr/Tdarr_Node`; install the two Mac helper modules
listed in [TDARR.md](../docker/docs/TDARR.md) beside it under `Custom`.

Create a dedicated key in Tdarr **Tools -> API Keys**. Run
`sudo bash set-tdarr-api-key.sh` from a trusted copy on the Mac and paste it at
the hidden prompt, never into chat. The script writes as `_studio`, refuses
existing files/symlinks, and never exposes the value in argv or logs. Existing
node credentials were denied API-key creation (403); do not bypass that denial
with direct database edits. A separate key is revocable, not demonstrated
per-node least privilege. For rotation/revocation, first stop the native node;
do not assume an established socket is immediately invalidated.

For a future approved isolated deployment, load the transport daemon before
the Tdarr daemon. **The installed native Tdarr daemon is currently disabled;
do not enable it against the shared production controller.** `start-tdarr.sh` verifies
both mounts, supplies base64-encoded canonical path mappings, and starts paused
with one CPU transcode worker and zero GPU/health workers. Confirm actual
real/effective UID and the server's live pause/worker settings after startup.
The headless system-daemon remount has been exercised; a cold-boot/FileVault
unlock and recovery test remains separate.

## Operations and rollout gates

The `studio-transfer` Compose profile is opt-in. Use the main production
Compose entry point, never a category file standalone:

```sh
z /srv/homeserver/docker
docker compose --profile studio-transfer up -d --no-deps \
  studio-media-share studio-transfer-relay studio-tdarr-relay
```

The initial deployment uses the production main file plus a private overlay
at `/srv/docker/data/studio-transfer/compose.studio.yml`; reconcile that overlay
and profile activation when the repository change lands. Likewise, the live
SSH Match block is currently a guarded root-owned shadow of the original Nix
symlink. Merge and activate its declarative Nix changes before relying on a
future Nix activation to preserve transport. Setup does not perform that
activation, restart Docker/Tdarr, or reboot either host.

**Native Tdarr rollout is blocked by the installed 3.07 staged scheduler.**
The copied-media attempt admitted 23 staged production TV jobs despite verified
live/persisted library exclusions. They failed before encoding when the Mac
could not create the unmapped `/temp/tdarr-workDir2-*` directories. The native
daemon was stopped and persistently disabled; the canary was disabled and the
temporary HomeServer tag restored. No successful canary encode or handoff
was demonstrated. See [the incident and scheduling boundary](../docker/docs/TDARR.md#prevent-the-mac-from-taking-existing-linux-only-jobs).

`librariesToNotProcess` filters fresh queued selection, **not staged selection**;
untagged staged work matches any node's tags. A frozen library inventory,
one worker, or successful settings readback therefore cannot authorize unpause.
Keep the native daemon disabled on the shared controller. A new attempt needs
explicit approval for either a separate canary-only controller/state and
dedicated Linux worker, or a verified scheduler fix covering both selection
paths. Export only disposable copied media/cache for that experiment, never the
whole production media tree, and include an eligible disposable decoy as a
negative scheduling test. New flow guards cannot protect already-staged old
continuations. Trusted Tdarr controllers/plugins remain part of the boundary;
this is not a malicious-node sandbox.

Speech and Ollama remain loopback-only under `_studio`. Speech timing checks
and automatic overlap metrics are not human-reviewed translation accuracy.
Production Bazarr still needs the provider-status patch, authenticated
transport, multi-audio integration, and quality approval before any switch.

`home.arpa` belongs at `/etc/resolver/home.arpa`, root-owned and LF-terminated.
It scopes resolution to the homeserver's DNS; AdGuard provides
`ai-studio.home.arpa` and `homeserver.home.arpa`. Preserve pinned SSH host keys
when updating administrative aliases.

Colima runs separately as `dante` with 4 CPUs, 6 GiB RAM and a 60 GiB ARM64 VZ
disk; its explicit shared directory is `~/Services/docker-shared`. Do not
mount the worker's credentials, administrator SSH directory or production
media into that VM.
