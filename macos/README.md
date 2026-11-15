# Mac Studio compute companion

The Studio runs native speech inference, an advisory local model, and a
**native Tdarr node that encodes TV episodes with CPU x265 for the server**: it
is installed and paused until the cutover (see
[the offload](../docker/docs/TDARR-STUDIO.md) and
[Installing and starting the Tdarr node](#installing-and-starting-the-tdarr-node)).
Docker (Colima) has been removed until a service needs it; see
[Docker](DECISIONS.md#docker). Bazarr's Whisper subtitles are moving to the
Studio ([status](ai/README.md#bazarr-transport-and-cutover)). The Mac never
replaces original media: the server validates each encode and publishes it.

See [speech setup](ai/README.md), [model comparisons and limitations](ai/SPEECH.md),
[the Tdarr offload](../docker/docs/TDARR-STUDIO.md) and
[Tdarr's storage-authoritative flow](../docker/docs/TDARR.md). Start with
[intents and decisions](DECISIONS.md): it records what Dante wants, which
pieces an agent chose, and how to remove each piece.

## Identities and private transport

| Component | Identity / boundary |
|---|---|
| Native speech, Ollama, Tdarr, SSH transport | `_studio`, private `/var/lib/studio-worker` home, no admin/wheel/SSH-login access |
| Mac administrative SSH | `dante`; never lend this account's private key to `_studio` |
| Linux SSH transport | `studio-tunnel`, nologin, dedicated key, no shell/PTY/SFTP, reverse/agent/Unix-socket forwarding |
| Linux SMB account | `studio`; original media read-only, only the dedicated native job cache writable |
| Linux fixed TCP relays | UID/GID 65534, read-only root, no capabilities, no-new-privileges, no mounts or credentials |
| Bazarr → Mac speech | Mac `_bazarr`: hidden, no password/shell/home, outside admin/wheel; key restricted to the server's address and a local forward to `127.0.0.1:9000`. Linux `studio-whisper` container: `HOST_UID`, read-only root, no capabilities, network shared only with Bazarr |

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

`mount-studio-share.c` is built on the Mac. The Tdarr installer
([below](#installing-and-starting-the-tdarr-node)) does it on every run; to build
it by hand:

```sh
clang -Wall -Wextra -Werror -O2 \
  -framework CoreFoundation -framework NetFS \
  mount-studio-share.c -o mount-studio-share
```

The binary belongs to `_studio` in its private home (the installer uses mode
0755; the home itself is 0700). Create private
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
| `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-launcher` (built from `studio-tdarr-launcher.c`) | root:wheel 0755; holds the [Full Disk Access](#full-disk-access-for-the-nodes-launcher) grant |
| `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-session` (from `start-tdarr-session.sh`) | root:wheel 0755 |
| `/Library/PrivilegedHelperTools` and protected ancestor directories | root-owned, no worker write access or replaceable links/ACLs |
| `/Library/LaunchDaemons/com.danteb.studio-tdarr.plist` | root:wheel 0644 |
| `/var/log/studio-tdarr` | root:wheel 0700; only regular root-owned log files |
| Worker home | `_studio`, 0700 |
| `start-tdarr.sh` and `mount-studio-share` in the worker home | `_studio` 0755, written by the worker itself (inside the 0700 home) |
| Worker `tdarr-api-key` and SMB credential file | `_studio`, 0600 |
| Worker `tdarr/Custom` modules (`hevc-offload-v1.cjs`, `hevc-safe-v1.cjs`, `dv5-sidecar.cjs`) | `_studio` 0644, written by the worker itself. Root ownership would not protect them (the worker owns their directory); the server re-validates everything the Mac produces |

Never put root-executed launcher code or root-opened log paths in the
worker-writable home. Copy/extract the native ARM64 bundle **as the worker**,
not with a recursive root chown of a worker-writable tree. Its executable is
`/var/lib/studio-worker/tdarr/Tdarr_Node` and its version must match the
server's Tdarr (3.07.00 at the time of writing); the installer puts the three
Mac helper modules beside it under `Custom`.

Create a dedicated key in Tdarr **Tools -> API Keys**. Run
`sudo bash set-tdarr-api-key.sh` from a trusted copy on the Mac and paste it at
the hidden prompt, never into chat. The script writes as `_studio`, refuses
existing files/symlinks, and never exposes the value in argv or logs. Existing
node credentials were denied API-key creation (403); do not bypass that denial
with direct database edits. A separate key is revocable, not demonstrated
per-node least privilege. For rotation/revocation, first stop the native node;
do not assume an established socket is immediately invalidated.

### Installing and starting the Tdarr node

Load the transport daemon (`com.danteb.studio-transfer`) first, and have the
node bundle, SMB credential and API key in place. Then, as root from copies of
`macos/` and `docker/tdarr/` on the Studio:

```sh
sudo bash macos/install/install-tdarr-node.sh --modules docker/tdarr          # install or update
sudo bash macos/install/install-tdarr-node.sh --modules docker/tdarr --start  # (re)start the daemon
sudo bash macos/install/install-tdarr-node.sh --stop                          # stop and disable it
```

Every run first checks all its inputs and builds the mount helper in a
root-owned staging directory; nothing is replaced until those checks and builds
pass, so a failure changes nothing. Root then writes only root-owned paths: the
session script, the plist, the log directory and, only when it is missing, the
launcher. The worker's own files (`mount-studio-share`, `start-tdarr.sh` and,
with `--modules`, the three worker modules) are written **by the worker** from
that staging directory. The worker owns its home, and Apple's `install` (per its
open-source implementation) re-opens its target by name after the rename, so a
root-run `install` there could be redirected by a symlink the worker plants while
it runs. An earlier installer left `tdarr/Custom` root-owned; the first run with
`--modules` moves it aside as `Custom.superseded.<date>`, and the worker cannot
delete root-owned files, so remove that with `sudo` when convenient. The
launcher is built and ad-hoc signed **only when it is missing**
(`--replace-launcher` overrides that); every run prints its CDHash and warns when
the Full Disk Access grant below is absent. A plain install does not restart a
running node, so new scripts take effect at the next `--start`.

`--start` unloads the daemon, enables it and boots it in, retrying the bootstrap
up to three times because launchd can still be tearing the old job down. `--stop`
unloads and disables it, then waits up to a minute for the `_studio` node, start
script and any share probe still running on the mounts to finish (a probe can
outlive the node by up to about 25 s); it exits 3 and lists whatever is left.
Either one aborts any encode running on the node.

`start-tdarr.sh` treats a hung SMB share like a failed one. Every probe runs
under a time limit and, at the deadline, is killed together with anything it
started. A share counts as healthy only if its path is a real mount (a mount
point sits on a different device than its parent, so the empty directory left by
a vanished mount cannot pass) and it answers a listing. A mount that no longer
answers is force-unmounted before the helper runs, because the helper accepts any
earlier mount. The script mounts each share (three attempts, with a
force-unmount and a `NetAuthSysAgent` reset between them), proves it can list and
read the media share and write the cache before it starts the node, and then runs
a watchdog that stops the node when a share dies (three failed checks a minute
apart: SIGTERM first, and SIGKILL only if that same node is still there 20 s
later), so launchd restarts and remounts it. The watchdog ends within a second of
the node exiting, and a check that finishes after the node has gone is not
counted as a failure. The node runs at
`nice -n 10`, starts **paused** (`startPaused=true`) and registers as
`Studio-Native` with one CPU transcode worker and no GPU or health-check workers.
Pause state and worker limits are changed from the server with the node
configurator ([Node settings](../docker/docs/TDARR-STUDIO.md#node-settings)).
Whether the server's stored limits or pause state win over the start script's
values after a re-registration is still one of the
[open checks](../docker/docs/TDARR-STUDIO.md#open-checks-before-cutover), so
confirm the real and effective UID and the live settings after every start. The
headless system-daemon remount has been exercised; a cold boot with FileVault
is covered only by the note in
[DECISIONS.md](DECISIONS.md#headless-and-back-on-its-own-after-power-loss).

The installer and the dead-mount handling above were written while the Studio was
unreachable. Their tests run the real scripts on Linux against stubs; they have
not run on macOS yet, and the
[checks to make on the Studio](../docker/docs/TDARR-STUDIO.md#studio-scripts-verified-only-on-linux)
come first.

### A wedged mount agent

`_studio`'s per-user `NetAuthSysAgent` can hang in `LsarLookupNames` and then
blocks every later mount for that account. `mount-studio-share` bounds its wait
(`alarm(60)`, exit status 142), and between its three attempts `start-tdarr.sh`
force-unmounts and kills the agent, which launchd respawns on demand. By hand,
as root: `pkill -KILL -u "$(id -u _studio)" -x NetAuthSysAgent`. Never take the
pid from `launchctl print`: a service that is not running reports `0`, and
`kill -KILL 0` kills the whole process group.

### Full Disk Access for the node's launcher

macOS privacy (TCC) denies every file open on the SMB mounts to a process tree
that a LaunchDaemon started: the node, ffmpeg and ffprobe all fail with
`Operation not permitted` although the mount, owner and mode are right. SSH
sessions work only because `sshd-keygen-wrapper` already holds Full Disk Access.
Apple binaries as the job's program (`bash`, `sudo`, `cron`) do not pass
responsibility on to their children, but a third-party program does, so the
daemon's program is a small launcher, `studio-tdarr-launcher.c`, and one grant
covers the whole chain below it:

`com.danteb.studio-tdarr` (root LaunchDaemon) → launcher →
`start-tdarr-session.sh` → `launchctl asuser` → `sudo -u _studio` →
`start-tdarr.sh` → `Tdarr_Node` → ffmpeg.

The launcher stays narrow. It must be started by launchd as root, takes exactly
one argument (a root-owned script directly in `/Library/PrivilegedHelperTools`
whose name starts with `com.danteb.studio-`, not group- or other-writable, with
no `..`) and runs it with `/bin/bash` and a minimal environment. Do not turn it
into a launcher for arbitrary commands.

**The grant is bound to the launcher's path and code hash, so never rebuild,
recompile, re-sign or replace it:** that voids the grant and the node loses its
mounts. The installer builds it once. If `studio-tdarr-launcher.c` ever has to
change, run it with `--replace-launcher` and repeat the grant.

To grant it (once), start the daemon so the node's smoke test tries to read a
share, then switch on `com.danteb.studio-tdarr-launcher` in System Settings >
Privacy & Security > Full Disk Access. Dante has to do this: `tccutil` cannot
grant it, `TCC.db` must not be edited, and a configuration profile can carry the
exception only through MDM. Check it read-only from an SSH session, which holds
Full Disk Access itself (`auth_value` 2 is allowed; the installer runs the same
query for the launcher and warns unless it gets 2):

```sh
sudo sqlite3 -readonly "/Library/Application Support/com.apple.TCC/TCC.db" \
  "select client,auth_value,auth_reason,datetime(last_modified,'unixepoch','localtime') from access where service='kTCCServiceSystemPolicyAllFiles'"
```

Denied (`auth_value` 0) rows for `siriactionsd`, Homebrew `ffmpeg` and `ffprobe`,
`smbd` and a few diagnostic probes are leftovers of the diagnosis and grant
nothing. Never run `tccutil reset SystemPolicyAllFiles` without naming a client:
it would also remove the SSH grant.

## Operations

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

**Tdarr cutover status.** The node is installed and paused, and the offload flow
is built and deployed but not yet in use. Tdarr's free tier ignores node
exclusions and tags, so work is kept apart by worker types, flows, worker limits
and library schedules instead, and the cutover waits for a canary-library run.
See [the free-tier limits and the 2026-11-13 incident](../docker/docs/TDARR-STUDIO.md#free-tier-limits-and-the-2026-11-13-incident),
[the open checks](../docker/docs/TDARR-STUDIO.md#open-checks-before-cutover) and
[the runbook](../docker/docs/TDARR-STUDIO.md#cutover-and-rollback). Trusted
Tdarr controllers and plugins remain part of the boundary; this is not a
malicious-node sandbox.

Speech and Ollama remain loopback-only under `_studio`. Speech timing checks
and automatic overlap metrics are not human-reviewed translation accuracy.
Bazarr reaches the speech adapter only through the forward-only `_bazarr`
SSH account and the server's `studio-whisper` container; see
[Bazarr transport and cutover](ai/README.md#bazarr-transport-and-cutover).
Multi-audio selection still follows Bazarr's provider defaults.

`home.arpa` belongs at `/etc/resolver/home.arpa`, root-owned and LF-terminated.
It scopes resolution to the homeserver's DNS; AdGuard provides
`ai-studio.home.arpa` and `homeserver.home.arpa`. Preserve pinned SSH host keys
when updating administrative aliases.
