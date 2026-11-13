# Mac Studio: intents, decisions and inventory

macOS setup is not declarative like `nixos/`: nothing rebuilds the Studio from
this repository, and hand-made changes are easy to lose track of. This file is
the Studio's record of **what Dante wants**, **how that is met today** and
**where every piece lives**, so any future agent (on the Windows PC, the Studio,
a MacBook or elsewhere) can audit, rebuild, improve or remove it. Update it in
the same change as any Studio change. Server cooling and hardware are in
[`docs/SERVER-COOLING.md`](../docs/SERVER-COOLING.md).

## How to read this

- **Intent** is Dante's goal and the actual requirement. His requests were
  mostly basic; they are kept close to his words.
- **Current** describes how the intent is met today. Unless marked *Dante*, an
  agent chose it and it is not a requirement. Replace it whenever something
  better meets the intent: remove the old pieces instead of layering on top,
  then update this file.

> "If in the future, an agent can better solve one of my requests, it should be
> allowed to clean up your work without feeling like I had my heart set on doing
> it that specific way." (Dante)

Operational detail: [`README.md`](README.md) (worker account, transport, Tdarr
install), [`ai/README.md`](ai/README.md) and [`ai/SPEECH.md`](ai/SPEECH.md)
(speech services and models), [`docker/docs/TDARR.md`](../docker/docs/TDARR.md).

## The machine and how to reach it

Dante bought this Mac Studio as a compute companion for the homeserver.

| | |
|---|---|
| Hardware | Mac Studio (`Mac17,14`, MHL64LL/A): Apple M5 Max, 18-core CPU, 36 GB unified memory, 512 GB SSD |
| OS | macOS 27.2.1, FileVault on |
| Network | Ethernet; router DHCP reservation `192.168.50.140` (*Dante*); DNS name `ai-studio.home.arpa` |
| Admin account | `dante`. Membership in macOS's `admin` group is what grants sudo; macOS does not use `wheel` for that |
| Remote access | SSH (port 22) and Screen Sharing (VNC, port 5900), both enabled by *Dante* |

| From | How | Key |
|---|---|---|
| Windows PC | `ssh ai-studio` (`hosts` maps the name to the IP) | `~/.ssh/id_ed25519` |
| MacBook Pro | Same `ai-studio` SSH profile (copied by *Dante*); Screen Sharing app | The MacBook's own key |
| Homeserver (`danteb`) | `ssh studio` | `~/.ssh/id_ed25519_studio` |
| Studio | `ssh homeserver` | `~/.ssh/id_ed25519` |

## Facts any replacement must handle

- **Tdarr 3.07 staged jobs ignore node exclusions.** Any extra node on the
  shared production controller can receive old production jobs, whatever its
  tags or library exclusions say ([details](#offload-video-encoding-tdarr)).
- Only the validated production flow may replace original media.
- Tdarr reports, node configs and backups can contain credentials. Never print
  or commit them.
- With FileVault on, nothing starts after a power loss (not even
  LaunchDaemons) until the disk is unlocked.
- Assume any router setting change reboots the router.
- On the server, never run `docker compose -f compose.<category>.yml up`.

## Headless, and back on its own after power loss

**Intent:** run without a monitor or keyboard, managed remotely, at a stable
address.

**Current**

- Remote Login (SSH), Screen Sharing and the DHCP reservation (*Dante*).
  Remote Management (Apple Remote Desktop) is not needed.
- Power (*Dante*): `pmset -g` shows `autorestartatconnect 1`, the macOS 26+
  setting that starts the Mac when power returns. This is correct. The legacy
  `autorestart 0` also shown is expected; do not change it. `sleep 0` and
  `womp 1` keep it awake and wakeable.
- FileVault: after a cold boot macOS waits at the pre-boot unlock. With Remote
  Login on, Apple supports unlocking it over SSH with the account **password**
  (`man apple_ssh_and_filevault`). The connection then drops, and normal
  key-only SSH works once macOS has started. This pre-boot step is separate from
  the sshd hardening below. **Not yet tested here.**

## SSH should be secure

**Intent:** "SSH should be secure" (Dante's examples: no password or root
login), and convenient: the keys allowed on the server may reach the Studio.
Follow current best practice; the mechanisms below are today's choice, not the
requirement.

**Current**

- [`admin/000-studio-hardening.conf`](admin/000-studio-hardening.conf) in
  `/etc/ssh/sshd_config.d/`: public keys only, no root login. It leaves Apple's
  `100-macos.conf` and PAM alone. The `000-` prefix wins because sshd keeps the
  first value it reads. macOS starts sshd per connection, so new logins use it;
  keep an existing session open while testing:

  ```sh
  sudo install -o root -g wheel -m 644 admin/000-studio-hardening.conf /etc/ssh/sshd_config.d/
  sudo sshd -t && sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|authenticationmethods|usepam) '
  ```

- `~/.ssh/authorized_keys` is a one-time copy of the server's keys from
  `nixos/modules/users.nix` (*Dante* wanted the same set). Nothing syncs them.
  The `WorkPC` and retired `DESKTOP-DD5K2PO` keys should be pruned (not done).
- Host-to-host: each host has its own key, so private keys never move between
  machines. They have no passphrase (automation) and are limited by
  `from="192.168.50.0/24"`. The Studio's key is in the server's live
  `authorized_keys` and declared in `users.nix`.
- The worker account `_studio` cannot log in over SSH
  ([`001-studio-worker.conf`](001-studio-worker.conf)).
- Alternative Dante raised: reach the Studio only through the server
  (`ProxyJump`).

## Shell like my other devices

**Intent:** Homebrew, zsh with Zim and fastfetch at sign-in, like Dante's other
devices.

**Current**

- Homebrew owned by `dante`. Formulae: `bat`, `fastfetch`, `zimfw`, `zoxide`;
  `ffmpeg`, `ollama` and `uv` serve the AI work.
- [`admin/`](admin/) holds the dotfiles: `zimrc` uses the server's Zim modules
  and asciiship prompt; `zshrc` runs fastfetch only for interactive login
  terminals, so scripted SSH and `scp` stay clean. Zim downloads its modules on
  the first shell. Machine-specific or secret settings belong in untracked
  `~/.zprofile.local` / `~/.zshrc.local`.

  ```sh
  brew install zimfw fastfetch zoxide bat
  for f in zshenv zprofile zimrc zshrc; do install -m 0644 admin/$f ~/.$f; done
  ```

## Names, not IPs

**Intent:** reach the Studio at a known name through AdGuard local DNS "so we
don't need to save random IPs in the server or the Mac".

**Current**

- AdGuard (on the server) rewrites `ai-studio.home.arpa` to `.140` and
  `homeserver.home.arpa` to `.100`. `home.arpa` is the suffix reserved for home
  networks (RFC 8375).
- On the Mac, [`home.arpa`](home.arpa) installed as `/etc/resolver/home.arpa`
  sends only that suffix to AdGuard.
- Verified resolving on Windows, the server host, Docker containers (Bazarr,
  NPM) and the Mac.

**Guidance:** use these names in new configuration (web services, Bazarr's
Whisper URL, notification hooks, SSH, Screen Sharing). Caveats:

- AdGuard runs on the server, so anything needed to repair the server should
  keep an IP or `hosts` fallback.
- Windows also lists 1.1.1.1 as a DNS server, which cannot answer `home.arpa`,
  so lookups can fail intermittently. The `hosts` entry covers `ai-studio`.
- When an SSH alias moves from an IP to a name, keep `HostKeyAlias` so the
  pinned host key still matches.

Not done: SSH aliases on all machines still use IPs.

## Exposing Studio services

Recommendation, not yet applied (Dante asked whether to use SSH tunnels or a
real reverse proxy):

- **Web UIs for people:** an NPM proxy host pointing at
  `http://ai-studio.home.arpa:<port>`, with Authelia when the app has no login.
  This matches the server's convention, and NPM resolves `home.arpa`.
- **APIs for machines** (Whisper for Bazarr, Ollama for automations): these
  apps have no authentication. Listen on the LAN but allow only the server's IP
  (macOS `pf`), or put a small reverse proxy that requires an API key in front.
  Authelia's login flow does not suit API clients.
- **SSH tunnels** only for server-only resources the Studio must not expose on
  the LAN (today: Samba and the Tdarr node port). For ordinary HTTP they add
  moving parts.

Today Whisper and Ollama listen only on the Studio's loopback, so nothing else
can use them yet.

## Offload speech-to-text (Whisper)

**Intent:** run Whisper subtitle work on the Studio instead of the server, with
good results for Dante's media: English, Japanese anime and Telugu mythological
films. Dante asked to try all three languages.

**Installed:** `mlx-whisper` 0.4.3 with `mlx-community/whisper-large-v3-mlx`
(pinned revision `49e6aa2`), behind an experimental Bazarr-compatible adapter:
LaunchDaemon `com.danteb.studio-whisper` as `_studio` on `127.0.0.1:9000`. It
turns off `condition_on_previous_text` for English transcription only.

**Tested on full episodes.** The score is how many word-bearing reference
subtitle cues overlap generated words. It measures timing coverage, not
whether the words are right.

| Model | English, 22m50s (630 cues) | Japanese → English, 22m51s (309) | Telugu → English, 46m36s (319) | Outcome |
|---|---|---|---|---|
| Whisper large-v3, default | 527, 70 s; punctuation loop | **304**, 104 s | **313**, 196 s; bad timestamps and repeats | Used for Japanese and Telugu |
| Whisper large-v3, previous-text conditioning off | **623** (621 through the service, 53 s) | 285 | 301; timestamps fixed, repeats remain | Used for English only |
| Qwen3-ASR 1.7B + aligner | 615, 54 s; three zero-length cues | Cannot translate | No Telugu | Close second for English; not a service |
| SeamlessM4T v2 | Not run | Hallucinated a short synthetic sentence | Correct on a short synthetic greeting | Not run on episodes; non-commercial licence, no timings |
| turbo, Parakeet, Omnilingual, IndicConformer | Not run | | | Ruled out on paper ([why](ai/SPEECH.md#candidates-and-constraints)) |

**Decision so far:** no production default. **Bazarr still uses the server's
Whisper.** Large-v3 is the best Studio candidate, but nobody has reviewed the
words. Before a cutover: a fluent human review, a way for Bazarr to reach the
service ([above](#exposing-studio-services)), multi-audio handling and the
provider patch in [`ai/`](ai/).

[`ai/compare_speech.py`](ai/compare_speech.py) computes these scores. The
reference and generated subtitles stay private on the Studio in
`~/Services/ai-staging/benchmark-20261113/`; they derive from copyrighted
media, so they are not in git.

## Local LLM for automations

**Intent:** local models that can later add judgement to maintenance
automations and notifications (for example, AI-enhanced notification events).

**Current:** Ollama with `qwen3:8b` (5.2 GB, Q4); LaunchDaemon
`com.danteb.studio-ollama` as `_studio` on `127.0.0.1:11434`; cloud features
off. Only a structured-output smoke test has run, and nothing uses it. An agent
picked the runtime and model; choose them for real when the first automation
exists.

## Offload video encoding (Tdarr)

**Intent:** move CPU-heavy encoding off the server (heat) without lowering
quality. *Dante* keeps quality-first CPU `libx265` encoding and cares about the
result, not the configuration.

**"Hardware encoders are not equivalent quality per byte"** is true:

- At the same bitrate, slow software x265 beats hardware encoders. Recent NVENC
  (including the server's RTX 2070 SUPER) is roughly comparable to faster
  software presets.
- Apple's VideoToolbox does not improve on NVENC. Comparisons rank x265, then
  NVENC, then VideoToolbox at equal bitrate. Its strengths are speed and low
  power; it has few tuning options, and HandBrake notes its scaler is less
  sharp. No M5-specific measurement was found.
- So the Studio plan used CPU `libx265` slow, not the media engine, matching
  [why the server uses CPU](../docker/docs/TDARR.md#why-cpu-libx265-instead-of-nvenc).

Sources: [HandBrake on VideoToolbox](https://handbrake.fr/docs/en/latest/technical/video-videotoolbox.html),
[M1 Pro `hevc_videotoolbox` vs `libx265`](https://yre.jp/en/post/m1mac_h265/),
[VMAF comparison of all three (Chinese)](https://blog.csdn.net/a18302465887/article/details/164360115).

**Current: not working, disabled.**

- Design (agent and a security reviewer): a native node as `_studio` reaches
  the server's controller through the SSH tunnel. The flow
  `homeserver-hevc-studio-v1` has Linux check the source, the Mac encode into a
  cache, then Linux validate and publish, so the Mac can never replace
  originals.
- **The controller/node split worked:** tunnel, registration and job delivery
  all functioned. **What failed was limiting which jobs the node takes** on the
  shared production controller. Tdarr 3.07 applies library exclusions
  (`librariesToNotProcess`) only when picking fresh queue items. Already-staged
  jobs skip that check, and untagged staged jobs match any node. The Mac took
  23 staged production TV jobs; each failed safely because it could not create
  Tdarr's `/temp/tdarr-workDir2-*` work folder. Nothing was encoded or
  replaced, and *Dante* chose to requeue the 23 jobs.
  [Incident details](../docker/docs/TDARR.md#prevent-the-mac-from-taking-existing-linux-only-jobs).
- The native daemon is disabled (`launchctl disable`). Keep it off on the
  shared controller.

**To retry, Dante chooses one:** a separate canary-only Tdarr controller with
disposable media; a verified upstream fix covering both fresh and staged
selection; or no Mac encoding (cap or schedule the server's encoders for heat
instead). Any retry needs a negative test with an eligible decoy job. Do not
drain or retag shared staging or pause production as a workaround.

## Isolating untrusted media work

FFmpeg and Tdarr parse untrusted media. *Dante* chose, from options an agent
offered: an SSH-protected media share (over Tdarr Pro or unmapped transfer),
the private Tdarr port forward, account isolation with Samba restrictions, and
the restricted launcher. Everything else here is agent or reviewer design and
the largest elaboration beyond the requests.

- Mac `_studio` (UID 499, private home `/var/lib/studio-worker`, no shell or
  SSH) runs Whisper, Ollama, the tunnel and Tdarr. `allow-worker-tools.sh`
  gives it read/execute ACLs on the Homebrew tools it needs.
- Server `studio-tunnel` (UID 993, nologin) may only forward to
  `127.0.0.1:1445` (Samba) and `:8266` (Tdarr).
- Server containers `studio-media-share` (Samba: media read-only, Studio cache
  writable) and two loopback-only socat relays.
- The Mac LaunchDaemon `com.danteb.studio-transfer` keeps the tunnel up; a
  NetFS helper mounts the share; a root launcher drops to `_studio` for Tdarr.

Simpler alternatives: a Tdarr Pro unmapped node (no share or tunnel; costs
money), or a read-only LAN share limited to the Studio's IP. If Mac encoding is
abandoned, remove the tunnel, mounts, relays and Samba too; speech does not use
them.

## Docker

**Intent:** be ready to move services that suit the Studio, but "perhaps best
to remove Colima until we have a service that we want to run in Docker".
*Dante* prefers Colima to Docker Desktop.

**Current:** being removed; nothing ever ran in it. Dante asked on 2026-11-13
to remove Colima, the Docker CLI and the `com.danteb.colima` LaunchDaemon. If
`command -v colima` still prints a path, finish the removal:

```sh
sudo launchctl bootout system/com.danteb.colima
sudo rm -f /Library/LaunchDaemons/com.danteb.colima.plist
colima delete --force --data
brew uninstall colima docker docker-compose docker-buildx && brew autoremove
rm -rf ~/.colima ~/.docker ~/Services/docker-shared ~/Library/Caches/colima \
  ~/Library/Logs/studio-colima*.log
```

When a service is chosen, reinstall with `brew install colima docker docker-compose`
(old LaunchDaemon: `git show 7253f89:macos/com.danteb.colima.plist`). Share only
what the service needs, never the worker's home, admin SSH keys or production
media. MLX/Metal work cannot run inside Colima's Linux VM, so keep it native.
An agent suggested keeping storage, databases, *arr apps, DNS, NPM and auth on
the server.

## Where everything lives

### In git

| Path | Contents |
|---|---|
| `macos/admin/` | sshd hardening and dotfiles |
| `macos/` | Worker provisioning, `home.arpa` resolver, tunnel, share mount helper, Tdarr launcher and plists |
| `macos/install/` | The one-time installers as run on 2026-11-13 (they read from the deleted `~/Services/ai-staging`; the files they staged are in `macos/` and `macos/ai/`) |
| `macos/checks/` | Isolation checks: worker boundaries, share access, Tdarr node authentication |
| `macos/ai/` | Whisper adapter, Ollama and Whisper plists, Bazarr patch, `compare_speech.py`, `condition_false.py`, model evaluation |
| `docker/compose.studio.yml` | Server Samba share and relays (opt-in profile `studio-transfer`) |
| `docker/tdarr/` | Studio flow, its installer and the node restriction script |
| `nixos/modules/ssh.nix`, `users.nix` | `studio-tunnel` restrictions and the Studio's admin key |

### On the Studio

| Item | Location | Remove |
|---|---|---|
| Admin setup | `/etc/ssh/sshd_config.d/000-studio-hardening.conf`, `/etc/resolver/home.arpa`, dotfiles, `~/.ssh` | Keep unless replacing |
| Whisper, Ollama | `com.danteb.studio-whisper`, `com.danteb.studio-ollama`; models in the worker home | `sudo launchctl bootout system/<label>`, delete the plist and worker data |
| Tunnel and mounts | `com.danteb.studio-transfer`; mounts under `/private/var/lib/studio-worker/mounts/` | Unmount, `bootout`, delete the plist |
| Native Tdarr (disabled) | `com.danteb.studio-tdarr`, `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-session`, `/var/log/studio-tdarr`, worker `tdarr/` | Delete; optionally `sudo launchctl enable system/com.danteb.studio-tdarr` to clear the flag |
| Worker account | `_studio`, `/var/lib/studio-worker`, `001-studio-worker.conf`, ACLs from `allow-worker-tools.sh` | Last: remove the ACLs (`ls -le`), `sudo dscl . -delete /Users/_studio`, delete the home and conf |
| Benchmark subtitles (keep) | `~/Services/ai-staging/` (only `.srt`/`.ass` remain: `benchmark-20261113/`, `baseline/`, `qwen/`); inputs for re-runs in the worker's `ai-tests/benchmark-20261113/` | Keep until a speech default is chosen |
| Qwen comparison (needs sudo to remove) | Worker `ai-tests/models/` and its `mlx-qwen3-asr` uv tool | `sudo rm -rf /var/lib/studio-worker/ai-tests/models` and `sudo -u _studio env HOME=/var/lib/studio-worker /opt/homebrew/bin/uv tool uninstall mlx-qwen3-asr` |

Deleted with Dante's approval on 2026-11-13 (about 16 GB): the admin's Hugging
Face and uv caches, the duplicate Tdarr download, and the staging folder's
venv, audio and script copies (scripts not already in git were moved to
`macos/install/`, `macos/checks/` and `macos/ai/`).

### On the homeserver

| Item | Location | Remove |
|---|---|---|
| Samba and relays | `studio-media-share`, `studio-transfer-relay`, `studio-tdarr-relay`, started with the private overlay `/srv/docker/data/studio-transfer/compose.studio.yml` (holds the `samba.env` secret) | `docker rm -f` the three, remove their networks, delete `/srv/docker/data/studio-transfer` and the cache dir. A main-file `up --remove-orphans` also removes them |
| sshd | `/etc/ssh/sshd_config` is a root-owned copy shadowing the Nix symlink, plus a `studio-tunnel` Match block; backups in `/var/backups/studio-transfer/` | Restore the Nix symlink and reload sshd. Once `ssh.nix` with the same Match block is on `main`, a NixOS activation does this and keeps the tunnel; before that, activation drops the block (the tunnel fails closed) |
| Tunnel account | `studio-tunnel`, `/etc/ssh/studio-transfer-keys` | `userdel`, delete the file, drop it from `users.nix`/`ssh.nix` |
| Studio admin key | `~/.ssh/authorized_keys`, `users.nix` | Delete the line |
| Tdarr | `Studio-Native` node, canary library and flow, dedicated API key, snapshots in `/srv/docker/data/tdarr/server/Tdarr/Custom/backups/` (mode 0600; may hold credentials) | Delete in the UI and revoke the key |
| AdGuard | Two `home.arpa` rewrites | AdGuard UI, DNS rewrites |

## Open items

1. Cold-boot test, including the FileVault pre-boot SSH unlock.
2. Prune retired SSH keys on the Studio (and the server if retired there too).
3. Move SSH aliases and other configs to `home.arpa` names.
4. Speech: human review, then decide the Bazarr cutover and how Bazarr reaches
   the Studio.
5. Ollama: pick a first automation, or remove it.
6. Tdarr: choose a retry option or abandon it. If abandoned, remove Tdarr, the
   tunnel, mounts, relays and Samba.
7. Finish removing Colima, and the Qwen comparison if not needed (both need
   sudo; see [Docker](#docker) and the table above).
8. Merge [#205](https://github.com/dantebarbieri/homeserver/pull/205) so agents
   elsewhere can find this, then check the server's sshd file is the Nix symlink
   and reconcile the private Compose overlay with `compose.studio.yml`.
