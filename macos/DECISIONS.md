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

- **Tdarr's free tier ignores node tags and library exclusions** (they are Pro
  features; the API stores them anyway). Any node on the shared production
  controller can be given any library's work, so isolation has to come from
  flows, worker limits and library schedules
  ([details](#offload-video-encoding-tdarr)).
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
- 2026-11-14: a loose power cable cut the Studio's power (a hard power loss, not
  a shutdown) while the Tdarr offload was being prepared. After the cable was
  re-seated it stayed off the network (no ping, SSH or Screen Sharing) for
  hours; after a forced shutdown the status light pulsed white, Apple's sleep
  indicator. Whether it was waiting at the FileVault unlock is not confirmed
  yet. Secure the power connection (a UPS would also ride out an outage): an
  unplanned power loss needs someone at the machine, and how the offload behaves
  while the Studio is gone is an open check (see
  [Offload](#offload-video-encoding-tdarr)).

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
- Bazarr's forward-only account `_bazarr` can log in only with the server's
  key from the server's address, and can only forward to the Whisper adapter
  ([`ai/002-bazarr-forwarding.conf`](ai/002-bazarr-forwarding.conf),
  [setup](ai/README.md#bazarr-transport-and-cutover)).
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

Dante asked whether to use SSH tunnels or a real reverse proxy. Bazarr's
Whisper connection now uses a server-only SSH forward
([below](#offload-speech-to-text-whisper)); the rest is a recommendation not
yet applied. DNS naming and transport are independent: use
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

Today Whisper and Ollama listen only on the Studio's loopback. Only Bazarr
reaches Whisper, through its SSH forward; nothing reaches Ollama.

## Offload speech-to-text (Whisper)

**Intent:** run Whisper subtitle work on the Studio instead of the server, with
good results for Dante's media: English, Japanese anime and Telugu mythological
films. Dante asked to try all three languages.

**Installed:** `mlx-whisper` 0.4.3 with `mlx-community/whisper-large-v3-mlx`
(pinned revision `49e6aa2`), plus faster-whisper 1.2.1 with the server's
`Systran/faster-whisper-large-v3` (revision `edaa852`) for Telugu, behind a
Bazarr-compatible adapter:
LaunchDaemon `com.danteb.studio-whisper` as `_studio` on `127.0.0.1:9000`. It
turns off `condition_on_previous_text` for English transcription only.
The worker now applies bounded SRT timing repair (reordering, overlap trimming
and estimated ends) with sanitized repair counts; excessive or unsalvageable
timing defects still fail closed. These repairs do not verify audio alignment
or correct the words.

**Initial Studio-only tests on full episodes.** The score is how many word-bearing reference
subtitle cues overlap generated words. It measures timing coverage, not
whether the words are right.

| Model | English, 22m50s (630 cues) | Japanese → English, 22m51s (309) | Telugu → English, 46m36s (319) | Outcome |
|---|---|---|---|---|
| Whisper large-v3, default | 527, 70 s; punctuation loop | **304**, 104 s | **313**, 196 s; bad timestamps and repeats | Used for Japanese and Telugu |
| Whisper large-v3, previous-text conditioning off | **623** (621 through the service, 53 s) | 285 | 301; timestamps fixed, repeats remain | Used for English only |
| Qwen3-ASR 1.7B + aligner | 615, 54 s; three zero-length cues | Cannot translate | No Telugu | Close second for English; not a service |
| SeamlessM4T v2 | Not run | Hallucinated a short synthetic sentence | Correct on a short synthetic greeting | Not run on episodes; non-commercial licence, no timings |
| turbo, Parakeet, Omnilingual, IndicConformer | Not run | | | Ruled out on paper ([why](ai/SPEECH.md#candidates-and-constraints)) |

**Subsequent same-input comparison and AI word review:**
[`ai/COMPARISON.md`](ai/COMPARISON.md) compares both deployed endpoints on
Brooklyn Nine-Nine S01E01 (English), Parasyte S01E01 (Japanese), and Vishnu
Puran (2003) S01E01 (explicit Telugu audio). Studio English was faster
(54.8 vs 106.0 seconds) and the preferable proofread fallback draft in this
test. Neither Japanese output was good enough unattended. Studio Telugu
initially returned HTTP 422 for invalid timing; the server returned materially
unreliable translation despite HTTP 200. After the timing repair, a Studio-only
rerun on the same PCM returned valid SRT in 254.9 seconds, but its translation
was materially worse than the server's on this episode: substantially more
repetition, omitted dialogue and additional meaning reversals. The original
422 evidence is preserved separately. This is AI review against subtitle
references, not listening-based multilingual verification.

**Decision (*Dante*, 2026-11-13):** move Bazarr's Whisper work to the
Studio. English and Japanese were about as good or better there; for Telugu,
copy the server's approach to get as close as possible, and accept some loss
because "Telugu is a minority of subs". This supersedes his earlier condition
that Telugu first match the server.

**Current (agent-chosen):**

- Telugu input runs faster-whisper on the CPU with the server's model
  snapshot and decoding (beam size 5); MLX Whisper has no beam search.
  Everything else stays on MLX. Results: [Telugu on the CPU](ai/SPEECH.md#telugu-on-the-cpu).
- Bazarr uses a patched image ([`docker/dockerfiles/bazarr`](../docker/dockerfiles/bazarr))
  that rejects HTTP errors instead of saving them as subtitles. The build
  fails, keeping the previous container, if the patch stops matching upstream.
- Bazarr reaches the Studio's loopback adapter through the server's
  `studio-whisper` SSH forward as the forward-only Mac account `_bazarr`
  ([transport](ai/README.md#bazarr-transport-and-cutover)). An
  authenticated TLS proxy would also work; SSH reuses existing tooling and
  needs no certificates.
- **Cut over on 2026-11-13:** Bazarr's live endpoint is
  `http://studio-whisper:9000`, with a 30,000-second job timeout; its existing
  60-second connection timeout and all other settings were preserved.
  The installed Bazarr provider completed language detection, English
  transcription and Telugu-to-English translation through that endpoint.
  Both subtitle responses had valid, nonoverlapping timing. These bounded
  checks did not write library subtitles or establish translation quality.
  The original server `whisperasr` remains running for rollback.
- Bazarr still picks the first audio stream of multi-audio files when no
  audio language matches; audio-language preferences were not changed.

Timing overlap and API success are not quality approval, and this is AI
review against subtitle references, not listening-based verification.

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

**Intent:** move CPU-heavy encoding off the server, which gets hot and noisy,
onto the cooler Studio, to save server storage by re-encoding less important
files (mostly individual TV episodes) with minimal or no loss in perceptual
quality. Tdarr keeps scanning and choosing candidates on the server; only the
encode moves. *Dante* keeps quality-first software `libx265` and cares about
the result, not the configuration: the existing Tdarr flows and settings need
not be preserved. Speed is not the constraint (the array has about 13 TiB
free), so a slow, high-quality encode is preferred to a fast one that looks
worse. He authorized the move once it is validated, which supersedes the earlier
rule not to activate the node or pause production; a planned, announced pause or
drain is acceptable.

**Encoder fact-check (2026-11-14): software beats hardware per byte.** Measured
on this Studio (M5 Max, FFmpeg 9.0.2, x265 4.3) over eight library clips, scored
with VMAF (including the NEG variant and worst-frame scores) and CAMBI banding:
at equal VMAF, `hevc_videotoolbox` needs about 41% (quality mode, q65) to 101%
(average-bitrate mode) more bytes than x265 `slow`, and its worst frames score
far lower. x265 `medium` costs about 34% more bytes than `slow`, which is
roughly where published comparisons place this server's RTX 2070 NVENC (not
benchmarked here). Caveats: the scores are metrics, not a viewing test; eight
clips; speeds are approximate. The recipe stays x265 `slow` at CRF 20 in the
source's pixel format
([the server's flow](../docker/docs/TDARR.md#why-cpu-libx265-instead-of-nvenc)).
Variants (10-bit about 10% fewer bytes, `slower` 4% fewer for 3-10x the time,
`tune animation` 12% fewer), method and sources:
[TDARR-STUDIO.md](../docker/docs/TDARR-STUDIO.md#encoder-choice-software-x265).
CRF/CQ numbers are not interchangeable across encoders.

**Current: built and deployed, not yet active (2026-11-14).**

- Design (agent, with a security reviewer): the Tdarr server, queue, UI and every
  integrity check stay on the server. A *mapped* node as `_studio` encodes
  through a read-only media share and a cache-only writable share (the SSH tunnel
  to loopback relays described below); Linux then re-validates the result and
  publishes it with the unchanged `hevc-safe-v1.cjs` logic, so the Mac can never
  replace originals. The flow is `homeserver-hevc-offload-v1`; its design,
  runbook and open checks are in
  [TDARR-STUDIO.md](../docker/docs/TDARR-STUDIO.md).
- Status: the node is installed and starts paused, and the server still encodes
  the TV libraries on its own CPUs. The cutover waits for a canary-library run
  and the other
  [open checks](../docker/docs/TDARR-STUDIO.md#open-checks-before-cutover). An
  isolated lab passed a complete Mac encode and the Linux handoff.
- **Per-node library exclusions and node tags are Tdarr Pro features, as are
  unmapped nodes.** The free tier stores and reads back the settings but ignores
  them. On 2026-11-13 the Mac took 23 already-staged production TV jobs despite
  verified exclusions; each failed safely creating Tdarr's unmapped work folder,
  nothing was encoded or replaced, and *Dante* chose to requeue them.
  [Incident](../docker/docs/TDARR-STUDIO.md#free-tier-limits-and-the-2026-11-13-incident).
- **The machines are told apart by worker type.** Linux keeps no CPU transcode
  workers and one GPU-type slot that feeds the Mac and publishes its output; the
  Mac has only CPU workers. A staged job resumes after the last plugin that
  completed, so `Tags: Worker Type` gates hand a job across in both directions
  without Pro. The DV5 movie flow opens with such a gate so the Mac cannot take
  Linux-only work.
- **macOS privacy (TCC) blocks the node in a daemon context**, and the per-user
  mount agent can wedge. The launcher and its one-time Full Disk Access grant
  fix the first ([Isolating untrusted media work](#isolating-untrusted-media-work));
  `start-tdarr.sh` bounds and clears the second
  ([README](README.md#a-wedged-mount-agent)).
- Isolated lab (2026-11-13, removed): a 475 MiB x264 episode encoded in 39m18s
  into a larger file (582,779 KiB from 498,226,784 bytes), so Linux validation
  kept the original. Its server containers, networks, copied media/cache/state
  and temporary SSH forward were removed, and authorized cleanup removed its
  Studio-side files (listed under [On the Studio](#on-the-studio)).

**Next:** run the open checks in the canary library, then cut over with the
runbook in [TDARR-STUDIO.md](../docker/docs/TDARR-STUDIO.md#cutover-and-rollback),
which also covers rollback. Agents may replace any of these mechanisms with
something that meets the intent more simply.

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
  NetFS helper mounts the share. The Tdarr LaunchDaemon `com.danteb.studio-tdarr`
  runs a small root-only launcher that takes only the path of a root-owned
  session script directly in `/Library/PrivilegedHelperTools` and runs nothing
  else; that script drops to `_studio` for the node.
- **The launcher holds the one privacy exception the node needs: Full Disk
  Access.** macOS privacy (TCC) denies every file open on the SMB mounts to a
  daemon's process tree unless a third-party launcher holding the grant leads it
  ([why and how](README.md#full-disk-access-for-the-nodes-launcher)). The grant
  is bound to the file's path and code hash, so **never rebuild, re-sign or
  replace the launcher.** Installed 2026-11-14 with CDHash
  `951ac16ad48cee8d87d71678b30d87ed91207bf9`. A few harmless denied TCC entries
  (`auth_value` 0, such as `smbd`, Homebrew `ffmpeg` and `siriactionsd`) remain
  from the diagnosis.

Simpler alternatives: a Tdarr Pro unmapped node (no share or tunnel; costs
money, and Pro would also honor node tags and library exclusions), or a read-only
LAN share limited to the Studio's IP. If Mac encoding is abandoned, remove the
tunnel, mounts, relays and Samba too; speech does not use them.

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
| `macos/` | Worker provisioning, `home.arpa` resolver, tunnel, share mount helper, the Tdarr launcher (C source), session and start scripts, and plists |
| `macos/install/` | `install-tdarr-node.sh` installs or updates the Studio's Tdarr node and is safe to rerun (it builds the launcher only when missing). The other installers are historical one-time scripts from 2026-11-13, not ready-to-rerun provisioning: their staging inputs and comparison models were removed; reusable sources are in `macos/` and `macos/ai/` |
| `macos/checks/` | Isolation checks: worker boundaries, share access, Tdarr node authentication |
| `macos/ai/` | Whisper adapter, Ollama and Whisper plists, `_bazarr` sshd drop-in and provisioning script, comparison/review helpers, model evaluation and `COMPARISON.md` findings |
| `docker/compose.studio.yml` | Server Samba share and relays (opt-in profile `studio-transfer`) |
| `docker/compose.ai.yml`, `docker/dockerfiles/studio-whisper-tunnel/` | Bazarr's SSH forward to the Studio's Whisper adapter |
| `docker/dockerfiles/bazarr/` | Patched Bazarr image (rejects Whisper HTTP errors) |
| `docker/tdarr/` | The offload module and flow installer, the node-settings configurator and the update-lease script (the rest is the server's own Tdarr tooling) |
| `nixos/modules/ssh.nix`, `users.nix` | `studio-tunnel` restrictions and the Studio's admin key |

### On the Studio

| Item | Location | Remove |
|---|---|---|
| Admin setup | `/etc/ssh/sshd_config.d/000-studio-hardening.conf`, `/etc/resolver/home.arpa`, dotfiles, `~/.ssh` | Keep unless replacing |
| Whisper, Ollama | `com.danteb.studio-whisper`, `com.danteb.studio-ollama`; models in the worker home | `sudo launchctl bootout system/<label>`, delete the plist and worker data |
| Bazarr forwarding account | `_bazarr`, `/etc/ssh/sshd_config.d/002-bazarr-forwarding.conf`, `/etc/ssh/bazarr-forwarding-keys`, membership in `com.apple.access_ssh` | [Transport removal](ai/README.md#bazarr-transport-and-cutover) |
| Tunnel and mounts | `com.danteb.studio-transfer`; mounts under `/private/var/lib/studio-worker/mounts/` | Unmount, `bootout`, delete the plist |
| Native Tdarr node (installed, paused until the cutover) | `com.danteb.studio-tdarr` (plist in `/Library/LaunchDaemons`), the launcher and session script `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-{launcher,session}`, `/var/log/studio-tdarr`, worker `tdarr/` (node and `Custom/` modules), the launcher's Full Disk Access entry in System Settings | `sudo bash macos/install/install-tdarr-node.sh --stop` boots it out and disables it. To remove it, delete those files and the launcher's Full Disk Access entry; optionally `sudo launchctl enable system/com.danteb.studio-tdarr` to clear the disabled flag |
| Isolated Tdarr lab (removed 2026-11-13) | `/Library/LaunchDaemons/com.danteb.tdarr-lab-node.plist`, `/Library/LaunchDaemons/com.danteb.tdarr-lab-mount-media.plist`, `/Library/LaunchDaemons/com.danteb.tdarr-lab-mount-cache.plist`; `/var/lib/studio-worker/tdarr-lab-SfSmBI8k`; `/var/log/tdarr-lab-SfSmBI8k` | Removed after explicit authorization. Preflight found regular files/directories only, no symlinks or special files; post-check confirmed all five targets absent |
| Worker account | `_studio`, `/var/lib/studio-worker`, `001-studio-worker.conf`, ACLs from `allow-worker-tools.sh` | Last: remove the ACLs (`ls -le`), `sudo dscl . -delete /Users/_studio`, delete the home and conf |
| Initial benchmark subtitles (keep) | `~/Services/ai-staging/benchmark-20261113/`, `baseline/`, `qwen/`, and `/var/lib/studio-worker/ai-tests/`; only `.srt`/`.ass` files remain in these initial test directories | Keep until a speech default is chosen |
| Same-input comparison evidence | `~/Services/ai-staging/comparison-20261113/`: re-extracted PCM, references, endpoint outputs/errors, source manifest, timings and runtime fingerprints | Keep private for review; do not overwrite previous outcomes |
| Telugu timing-repair rerun | `~/Services/ai-staging/telugu-repair-20261113-v2/`: new response, HTTP metadata and review metrics; previous adapter/worker backups in `/var/lib/studio-worker/ai-tests/telugu-repair-20261113/` | Keep private and separate from the initial failed request |
| Telugu faster-whisper route | Model in the worker's Hugging Face cache (`models--Systran--faster-whisper-large-v3`, 2.9 GiB); pre-route adapter code in `/var/lib/studio-worker/ai-tests/deploy-20261113-backup/`; trial outputs, plus a duplicate admin copy of the model in `hf/`, in `~/Services/ai-staging/telugu-faster-whisper-20261113/`; deployment staging in `~/Services/ai-staging/deploy-20261113/` | Restore the backup and `uv sync` to roll back. With approval, delete the trial's `hf/` and the deployment staging once results are recorded |

Deleted with Dante's approval on 2026-11-13: the admin's Hugging Face and uv
download caches, the worker's uv cache, the duplicate Tdarr download, staging
venv, benchmark audio, and duplicate scripts. Reusable scripts are in
`macos/install/`, `macos/checks/` and `macos/ai/`. The worker's
`ai-tests/models/asr` and `ai-tests/models/aligner` (6.1 GiB combined) and
`mlx-qwen3-asr` uv tool were also removed. This Qwen speech experiment is
separate from Ollama's **retained `qwen3:8b`** language model. The worker's
Whisper model, service environment and `mlx-whisper` tool are retained.

All 28 initial subtitle files retained their SHA-256 hashes through cleanup.
The later same-input comparison re-extracted audio into its separate private
directory above. An empty uv cache/lock directory may be recreated by uv and
is not a leftover model download.

### On the homeserver

| Item | Location | Remove |
|---|---|---|
| Samba and relays | `studio-media-share`, `studio-transfer-relay`, `studio-tdarr-relay`, started with the private overlay `/srv/docker/data/studio-transfer/compose.studio.yml` (holds the `samba.env` secret) | `docker rm -f` the three, remove their networks, delete `/srv/docker/data/studio-transfer` and the cache dir. A main-file `up --remove-orphans` also removes them |
| sshd | `/etc/ssh/sshd_config` is a root-owned copy shadowing the Nix symlink, plus a `studio-tunnel` Match block; backups in `/var/backups/studio-transfer/` | Restore the Nix symlink and reload sshd. Once `ssh.nix` with the same Match block is on `main`, a NixOS activation does this and keeps the tunnel; before that, activation drops the block (the tunnel fails closed) |
| Tunnel account | `studio-tunnel`, `/etc/ssh/studio-transfer-keys` | `userdel`, delete the file, drop it from `users.nix`/`ssh.nix` |
| Studio admin key | `~/.ssh/authorized_keys`, `users.nix` | Delete the line |
| Bazarr's Whisper link | `studio-whisper` container; key and pinned Studio host key in `/srv/docker/data/studio-whisper-tunnel`; Bazarr's `whisperai` endpoint and timeout | Point Bazarr back at `whisperasr`, then [remove the transport](ai/README.md#bazarr-transport-and-cutover) |
| Bazarr migration rollback/evidence | `/srv/docker/data/bazarr/config/studio-migration-20261113/`: pre-cutover config and SQLite backup, aggregate `smoke-result.json`; original image tagged `bazarr-before-studio:20261113` | Backups contain secrets; keep private. Endpoint rollback normally needs only the settings change, not database restoration |
| Tdarr | `Studio-Native` node, the disabled canary library `homeserver-hevc-studio-canary-v1` with its test media in `/data/media/tdarr-studio-canary`, the `homeserver-hevc-offload-v1` flow and worker modules in `Custom/`, dedicated API key, snapshots in `/srv/docker/data/tdarr/server/Tdarr/Custom/backups/` (mode 0600; may hold credentials) | `install-tdarr-offload.sh --rollback`, then delete the node, canary library and flows in the UI and revoke the key |
| AdGuard | Two `home.arpa` rewrites | AdGuard UI, DNS rewrites |

## Open items

1. Cold-boot test, including the FileVault pre-boot SSH unlock. The unplanned
   power loss on 2026-11-14 was the first real one; record what the unlock
   needed once the Studio is back (see [Headless](#headless-and-back-on-its-own-after-power-loss)).
2. Prune retired SSH keys on the Studio (and the server if retired there too).
3. Use `home.arpa` for future service integrations. Admin SSH migration is
   complete on the reachable hosts; the MacBook is intentionally unchanged.
4. Speech: Bazarr's cutover is complete
   ([details](ai/README.md#bazarr-transport-and-cutover)); decide whether to
   retire the server's rollback `whisperasr`. English remains a proofread
   fallback; Japanese and Telugu still need audio-grounded review, not more
   overlap scoring.
5. Ollama: pick a first automation, or remove it.
6. Tdarr: finish the canary-library checks, cut the TV libraries over and settle
   the Studio's worker count and x265 `pools`
   ([runbook](../docker/docs/TDARR-STUDIO.md#cutover-and-rollback)). Decide
   whether to secure the Studio's power (a UPS) or keep FileVault, since an
   unplanned power loss now stops the offload until someone unlocks the disk.
7. After the next NixOS activation, check the server's sshd file is the Nix
   symlink and reconcile the private transfer Compose overlay with
   `compose.studio.yml`. The Bazarr migration does not rebuild NixOS or
   change the Tdarr transfer setup.
