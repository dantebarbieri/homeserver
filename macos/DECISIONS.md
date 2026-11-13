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
- Approval of an agent-offered implementation does not make that mechanism
  an enduring requirement. Dante clarified this for service isolation and
  container tooling: the goals are secure services and suitable container
  management, not a particular account, tunnel or runtime.

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
| Windows PC | `ssh ai-studio` -> `ai-studio.home.arpa` (*Dante* updated the profile) | `~/.ssh/id_ed25519` |
| MacBook Pro | Existing `ai-studio` SSH profile; Screen Sharing app. Left unchanged at *Dante's* request | The MacBook's own key |
| Homeserver (`danteb`) | `ssh studio` -> `ai-studio.home.arpa` | `~/.ssh/id_ed25519_studio` |
| Studio | `ssh homeserver` -> `homeserver.home.arpa` (port 28) | `~/.ssh/id_ed25519` |

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
- Admin SSH profiles now use the names on Windows, the Studio and the
  homeserver. The MacBook profile was deliberately left unchanged. This
  migration does not change the worker tunnel or any service endpoint.
  The Studio and server each retain their previous admin profile at
  `~/.ssh/config.before-home-arpa-20261113`.

**Guidance:** use these names in new configuration (web services, Bazarr's
Whisper URL, notification hooks, SSH, Screen Sharing). Caveats:

- AdGuard runs on the server, so anything needed to repair the server should
  keep an IP fallback. From the Studio:
  `ssh -o HostName=192.168.50.100 homeserver`. From the server:
  `ssh -o HostName=192.168.50.140 studio`. From Windows:
  `ssh -o HostName=192.168.50.140 ai-studio`.
- Windows also lists 1.1.1.1 as a DNS server, which cannot answer `home.arpa`,
  so lookups can fail intermittently. Its old short-name `hosts` entry does
  not cover the new FQDN; the explicit IP override above bypasses DNS.
- Keep host-key verification when changing names. Windows retains
  `HostKeyAlias ai-studio`, the server retains `HostKeyAlias studio`, and the
  Studio uses `HostKeyAlias [192.168.50.100]:28` to match its existing
  port-qualified known-host entry. That last value is the pinned identity,
  not the network destination; `HostName` controls DNS resolution.

## Exposing Studio services

Recommendation, not yet applied (Dante asked whether to use SSH tunnels or a
real reverse proxy). DNS naming and transport are independent: use
`home.arpa` with either. A private DNS name does not authenticate clients.

- **Web UIs for people:** an NPM proxy host pointing at
  `http://ai-studio.home.arpa:<port>`, with Authelia when the app has no login.
  This matches the server's convention, and NPM resolves `home.arpa`.
- **APIs for machines** (Whisper for Bazarr, Ollama for automations): these
  apps have no authentication. Prefer an authenticated TLS reverse proxy for
  shared HTTP access; an API key or client certificate can suit clients that
  cannot use Authelia's interactive login. A server-only SSH tunnel is also a
  secure option while there is just one consumer. An IP allowlist alone does
  not encrypt traffic or authenticate individual clients.
- **SSH tunnels** remain appropriate for private non-HTTP resources (today:
  Samba and the Tdarr node port); an HTTP reverse proxy does not replace them.

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

**Encoder fact-check:** do not assume equal quality per byte, but there is no
universal software > NVIDIA > Apple ranking.

- Slow software HEVC encoding generally favors compression efficiency over
  hardware encoding's speed and power advantages. HandBrake's controlled
  comparison illustrates that tradeoff, but uses an older GTX 1060, not this
  server's RTX 2070 SUPER (Turing). It is not a measurement of these machines.
- An M1 Pro comparison found better detail from x265 at similar output size
  for one clip. It did not test NVENC or the Studio's M5 Max. **Whether the
  Studio's hardware encoder improves on this NVENC is unverified**, not a
  demonstrated yes or no.
- Results depend on codec, chip generation, encoder settings, content and
  bitrate. HandBrake documents limited VideoToolbox tuning and a different
  scaler; scaler sharpness is not evidence of encoder compression quality.
- The current plan retains CPU `libx265` slow, matching
  [the server's configuration](../docker/docs/TDARR.md#why-cpu-libx265-instead-of-nvenc).
  To reconsider, compare identical clips at matched video bitrate, resolution
  and bit depth without scaling or tone-map differences; inspect the picture
  as well as metrics such as VMAF. CRF/CQ numbers are not interchangeable
  across encoders. No such local comparison has been run.

Sources: [HandBrake encoder comparison](https://handbrake.fr/docs/en/latest/technical/performance.html#performance-comparison-between-video-encoders),
[HandBrake on VideoToolbox](https://handbrake.fr/docs/en/latest/technical/video-videotoolbox.html),
[M1 Pro `hevc_videotoolbox` vs `libx265`](https://yre.jp/en/post/m1mac_h265/).

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

**Next:** Dante requested further work toward functioning Mac offload, not
abandonment or a particular isolation design. Agents may choose a secure
approach; candidates include a separate controller tested with disposable
media or a verified upstream fix covering both fresh and staged selection.
Any retry needs a completed encode/validation path and a negative test with an
eligible decoy job before production activation. Do not drain or retag shared
staging or pause production as a workaround.

## Isolating untrusted media work

**Intent:** services in general should be secure. This applies to FFmpeg and
Tdarr because they parse untrusted media, but is not limited to them.

**Current:** agents and a security reviewer chose the SSH-protected share,
private Tdarr port forward, account isolation, Samba restrictions and restricted
launcher. Dante approved the offered options without intending to prescribe
those mechanisms. All are replaceable if another approach meets the security
and data-preservation goals more simply.

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

**Intent:** use the best suitable way to manage containers on the Studio when
there is a service that needs them. Colima was an agent recommendation, not
Dante's preference over Docker Desktop or other runtimes. Dante requested its
removal until there is an actual container workload.

**Current:** removed on 2026-11-13. Before removal, the VM had no containers or
volumes, only the `hello-world` smoke-test image; no service depended on it.
Removed the `com.danteb.colima` LaunchDaemon and plist, VM and data disk,
Colima, Docker CLI, Compose, Buildx and Lima, plus their Studio-specific
configuration, shared directory, cache and logs. No Colima/Lima processes
remain. Native Whisper and Ollama remain installed and working.

When a service is chosen, evaluate its needs and the available runtimes rather
than automatically restoring Colima. If Colima is still appropriate, the old
LaunchDaemon is recoverable with
`git show 7253f89:macos/com.danteb.colima.plist`. Share only what the service
needs, never admin SSH keys or unrelated production media. MLX/Metal work
cannot run inside Colima's Linux VM, so keep it native. An agent suggested
keeping storage, databases, *arr apps, DNS, NPM and auth on the server.

## Where everything lives

### In git

| Path | Contents |
|---|---|
| `macos/admin/` | sshd hardening and dotfiles |
| `macos/` | Worker provisioning, `home.arpa` resolver, tunnel, share mount helper, Tdarr launcher and plists |
| `macos/install/` | Historical one-time installers from 2026-11-13, not ready-to-rerun provisioning: their staging inputs and comparison models were removed; reusable sources are in `macos/` and `macos/ai/` |
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
| Benchmark subtitles (keep) | `~/Services/ai-staging/` (`benchmark-20261113/`, `baseline/`, `qwen/`) and `/var/lib/studio-worker/ai-tests/`; only `.srt`/`.ass` files remain in both trees | Keep until a speech default is chosen |

Deleted with Dante's approval on 2026-11-13: the admin's Hugging Face and uv
download caches, the worker's uv cache, the duplicate Tdarr download, staging
venv, benchmark audio, and duplicate scripts. Reusable scripts are in
`macos/install/`, `macos/checks/` and `macos/ai/`. The worker's
`ai-tests/models/asr` and `ai-tests/models/aligner` (6.1 GiB combined) and
`mlx-qwen3-asr` uv tool were also removed. This Qwen speech experiment is
separate from Ollama's **retained `qwen3:8b`** language model. The worker's
Whisper model, service environment and `mlx-whisper` tool are retained.

All 28 subtitle files across the two trees retained their SHA-256 hashes
through cleanup. To repeat inference benchmarks, re-extract the input audio
from the original private media; the subtitle-overlap scorer still works on
the retained outputs. An empty uv cache/lock directory may be recreated by uv
and is not a leftover model download.

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
3. Use `home.arpa` for future service integrations. Admin SSH migration is
   complete on the reachable hosts; the MacBook is intentionally unchanged.
4. Speech: compare the deployed server and Studio stacks on identical episode
   audio, including AI review of words/meaning against references, not just
   timing overlap. That review is not audio-grounded proof of translation
   accuracy. Then decide the Bazarr cutover and how Bazarr reaches the Studio.
5. Ollama: pick a first automation, or remove it.
6. Tdarr: pursue a secure, validated Mac offload path, keeping the known-unsafe
   shared-controller node disabled during the retry.
7. Review [#205](https://github.com/dantebarbieri/homeserver/pull/205). The docs
   are already pushed on `dantebarbieri-server-cooling` and accessible from
   other machines; merging makes them available on the default branch. After
   deployment, check the server's sshd file is the Nix symlink and reconcile
   the private Compose overlay with `compose.studio.yml`.
