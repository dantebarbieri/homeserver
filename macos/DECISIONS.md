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

> **Reinstalled 2026-11-21 as `No-Face`** (*Dante*: new hardware, fresh
> macOS install, new admin account). Restored and verified end to end that
> night: hostname, SSH, DNS, shell, the `_studio` worker and its tool ACLs,
> Ollama with `qwen3.5:9b-q4_K_M` and `qwen3:8b`, the Whisper adapter with
> both pinned models and the `mlx-whisper` CLI, the `_bazarr`/`_arrmaint`
> forwarding accounts, and the server's two tunnels (re-pinned host key;
> previous `known_hosts` kept as `known_hosts.before-no-face-20261121`). New:
> [Tailscale BMC route and `wake`](#tailnet-bmc-access-and-wake).
> The Tdarr tunnel and disabled native node were restored the following day
> ([current status](#offload-video-encoding-tdarr)); historical mount and
> canary results are not evidence for this install. The benchmark/comparison
> files under `~/Services/ai-staging` were lost with the old disk.
>
> A temporary non-admin `copilot` account with passwordless sudo
> (`/etc/sudoers.d/zz-copilot-temp`, member of `com.apple.access_ssh`) did
> the overnight work; Dante removed it the same night.

| | |
|---|---|
| Hardware | Mac Studio (`Mac17,14`, MHL64LL/A): Apple M5 Max, 18-core CPU, 36 GB unified memory, 512 GB SSD |
| OS | macOS 27.2.1, FileVault on |
| Names | `ComputerName` and `LocalHostName` `No-Face` (Apple's mixed-case style, *Dante*); `HostName` left unset as on a fresh install. Part of Dante's Ghibli naming theme |
| Network | Ethernet `BC:89:C1:E2:01:2B`; router DHCP reservation `192.168.50.80` (*Dante*); DNS name `no-face.home.arpa`, with `ai-studio.home.arpa` kept as a transitional CNAME to it |
| Admin account | `dantebarbieri`. Membership in macOS's `admin` group is what grants sudo; macOS does not use `wheel` for that |
| Remote access | SSH (port 22) and Screen Sharing (VNC, port 5900), both enabled by *Dante* |

| From | How | Key |
|---|---|---|
| Windows PC | `ssh no-face` (or `ssh ai-studio`) -> MagicDNS `no-face.<tailnet>.ts.net`, or `no-face.local` while the PC's Tailscale is stopped; `HostKeyAlias no-face` | `~/.ssh/id_ed25519` |
| MacBook Pro | Not yet updated for the reinstall | The MacBook's own key |
| Homeserver (`danteb`) | `ssh studio` (or `ssh no-face`) -> `no-face.home.arpa`, `HostKeyAlias no-face` | `~/.ssh/id_ed25519_studio` |
| Studio | `ssh homeserver` -> `homeserver.home.arpa` (port 28) | `~/.ssh/id_ed25519` (`dantebarbieri@no-face`) |

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
- Maintenance's independent `_arrmaint` account has the same forward-only
  restrictions but can reach only Ollama at `127.0.0.1:11434`
  ([setup](ai/README.md#ollama-transport)); it cannot reach Whisper.
- Alternative Dante raised: reach the Studio only through the server
  (`ProxyJump`).

## Shell like my other devices

**Intent:** Homebrew, zsh with Zim and fastfetch at sign-in, like Dante's other
devices.

**Current**

- Homebrew owned by `dantebarbieri` (the admin account). Formulae: `bat`,
  `fastfetch`, `zimfw`, `zoxide`; `ffmpeg`, `ollama` and `uv` serve the AI work
  once restored.
- [`admin/`](admin/) holds the dotfiles: `zimrc` uses the server's Zim modules,
  without asciiship; the prompt comes from the shared
  [`shell/prompt.zsh`](../shell/prompt.zsh) (reads `user on host in dir`, the
  host coloured per Ghibli character) which `zshrc` sources after Zim.
  `zshrc` runs fastfetch only for interactive login terminals, so scripted SSH
  and `scp` stay clean. Zim downloads its modules on the first shell.
  Machine-specific or secret settings belong in untracked
  `~/.zprofile.local` / `~/.zshrc.local`.
- fastfetch keeps its default Apple logo for now; Dante will supply artwork for
  a custom one.

  ```sh
  brew install zimfw fastfetch zoxide bat
  sh admin/install-shell.sh   # dotfiles plus ~/.config/ghibli/prompt.zsh
  ```

## Names, not IPs

**Intent:** reach the Studio at a known name through AdGuard local DNS "so we
don't need to save random IPs in the server or the Mac".

**Current**

- AdGuard (on the server) rewrites `no-face.home.arpa` to `.80`,
  `ai-studio.home.arpa` to `no-face.home.arpa` (transitional CNAME), and both
  `calcifer.home.arpa` and `homeserver.home.arpa` to `.100`. `home.arpa` is the
  suffix reserved for home networks (RFC 8375).
- On the Mac, [`home.arpa`](home.arpa) installed as `/etc/resolver/home.arpa`
  sends only that suffix to AdGuard.
- Verified resolving on Windows, the server host, Docker containers (Bazarr,
  NPM) and the Mac.
- Admin SSH profiles use the names on Windows, the Studio and the
  homeserver; the MacBook profile has not been updated for No-Face. The
  server's profile is managed by Home Manager (`nixos/home/danteb.nix`) and
  the Studio's host key is pinned in `nixos/modules/ssh.nix`. Windows and the
  server keep their pre-No-Face profiles at
  `~/.ssh/config.before-no-face-20261121`.
- Windows's `ssh no-face` no longer uses AdGuard (*Dante*, 2026-11-21:
  "preferably the same one so that it works on lan or tailscale with one
  hostname"). It uses the MagicDNS name, which works at home too because
  Tailscale connects LAN peers directly (7 ms over Wi-Fi). A `Match` block
  falls back to Bonjour's `no-face.local` when
  `~/.ssh/tailscale-running.cmd` (`tailscale status --peers=false`) fails.
  Both paths were verified, including with Tailscale stopped. The previous
  profile is at `~/.ssh/config.before-magicdns-20261121`.

**Guidance:** use these names in new configuration (web services, Bazarr's
Whisper URL, notification hooks, SSH, Screen Sharing). Caveats:

- AdGuard runs on the server, so anything needed to repair the server should
  keep an IP fallback. From the Studio:
  `ssh -o HostName=192.168.50.100 homeserver`. From the server:
  `ssh -o HostName=192.168.50.80 studio`. Windows's `ssh no-face` needs no
  override (above).
- Windows also lists 1.1.1.1 as a DNS server, which cannot answer `home.arpa`,
  so lookups can fail intermittently. Its stale `hosts` entry
  (`192.168.50.140 ai-studio`) should be removed; the explicit IP override
  above bypasses DNS.
- Keep host-key verification when changing names. Windows and the server use
  `HostKeyAlias no-face`, and the Studio uses
  `HostKeyAlias [homeserver.home.arpa]:28` for the server. That value is the
  pinned identity, not the network destination; `HostName` controls DNS
  resolution.

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

Whisper and Ollama listen only on the Studio's loopback. Only Bazarr reaches
Whisper. The three *arr maintenance helpers reach Ollama through their
separate `studio-ollama` SSH forward on the private `arr-ai` Docker network.

## Tailnet: BMC access and wake

**Intent** (*Dante*, 2026-11-21): "get it onto hosted tailscale and lets get a
wake-pc running on the no-face machine too". The tailnet should reach the
server's BMC even while the server is down, and the Studio should be able to
wake the Windows PC like the server can. The tailnet-wide migration
(server, Windows, docs) is owned by `docs`/`nixos` changes outside this file.

**Intent** (*Dante*, 2026-11-23): replace `wake-pc` with a prettier tool that
has presets for every machine in the house, is installed on all of them, skips
the machine it runs on, and auto-updates from its own git repository.

**Current**

- Open-source `tailscaled` from Homebrew, installed as the boot-time
  LaunchDaemon `com.tailscale.tailscaled` by `tailscaled install-system-daemon`
  ([installer](install/install-tailscale.sh)). Tailscale's GUI variants only
  run after a user logs in; this one starts at boot with no login, though like
  everything else only after FileVault is unlocked. It copies the binary to
  `/usr/local/bin/tailscaled`, which `brew upgrade` does not update: rerun
  `sudo tailscaled install-system-daemon` after upgrading.
- Logged in as machine `no-face` (`100.94.21.37`), advertising only
  `192.168.50.50/32` (the BMC; route approved 2026-11-21), with
  `--accept-routes=false --accept-dns=false` so local routing and DNS stay on
  the LAN and AdGuard.
- No NAT, IP forwarding or pf rules are needed: on macOS `tailscaled` serves
  subnet routes through its userspace network stack, so the BMC sees ordinary
  connections from `192.168.50.80`. Verified from DANTE-PC: its route to
  `192.168.50.50` is via the Tailscale interface and HTTPS returns 200. (A pf
  NAT helper tried first matched no packets and was removed.)
- `/usr/local/bin/wake` is the `aarch64-apple-darwin` release of
  [dantebarbieri/wake](https://github.com/dantebarbieri/wake), installed by
  its `install/install.sh` (run with sudo), which also deleted the old
  `/usr/local/bin/wake-pc`. The root LaunchDaemon `com.danteb.wake-update`
  (`/Library/LaunchDaemons/com.danteb.wake-update.plist`) runs
  `wake self-update --quiet` daily at 04:15, logging to
  `/var/log/wake-update.log`. No-Face is on the same LAN, so the broadcast
  default works, and `wake all` skips No-Face itself. The `pc` preset's MAC is
  DANTE-PC's wired NIC, which must be plugged in: on 2026-11-21 it was
  disconnected and the PC was on Wi-Fi (`.190`), so a magic packet could not
  wake it. No-Face itself can only be woken from sleep (never from shutdown),
  and `pmset` has `sleep 0`, so its preset mostly reports status.

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
- Bazarr's **Test Connection** appends `/status` to the provider URL. The
  adapter route for that check returns the engine versions without running inference.
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
  The original server `whisperasr` was removed on 2026-11-14 (*Dante*) after
  detection, English transcription and the Telugu engine were rechecked from
  the Bazarr container through this endpoint.
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

**Current:** Ollama's `com.danteb.studio-ollama` LaunchDaemon runs as `_studio`
on `127.0.0.1:11434`, with cloud features off. The *arr maintenance integration
selects `qwen3.5:9b-q4_K_M` (6.6 GB); the original `qwen3:8b` (5.2 GB) is
retained. Both runtime and model remain agent-chosen implementations.

**Dante's requirement (2026-11-14):** reduce manual interventions and reliance
on the cloud "Lidarr queue watch" by using local decisions for Radarr, Sonarr
and Lidarr (possibly Bazarr later). He permits model-assisted removal and
blocklisting only when independent checks also agree.

**Implementation:** existing deterministic maintenance runs first, then a
bounded local decision layer can request native import/metadata retries,
recheck missing-file torrents, or remove confirmed imported orphan torrent
entries **without deleting any files**. The model cannot execute code, force
identity mappings, override profiles or delete library files. State, retries,
pre-execution checks and later verification live in the server helpers.
The new `_arrmaint` SSH account and server-only key give only the helpers
access to Ollama. Bazarr's subtitle work is unchanged. Production helpers run
in `auto` since 2026-11-14; at Dante's choice the cloud watch's 15-minute
schedule was disabled then (it remains available for manual runs).

The old model chose the expected action on 6/10 synthetic raw cases (7/10 with
thinking); the selected 9B GGUF model chose 10/10 with thinking off, around a
second per warm request. Hard code vetoes remain mandatory. The plain
`qwen3.5:9b` alias selected a runtime variant without structured-output support,
so the explicit quantized tag is deliberate. These results are not a general
safety or accuracy guarantee. See [scope, evaluation and rollout](../docker/docs/ARR-MAINT-AI.md).

## Offload video encoding (Tdarr)

**Production cutover, 2026-11-22:** Dante chose to move TV
encoding to No-Face while Calcifer keeps the Tdarr controller, Linux validation
and publication, and NVIDIA DV5 processing. The production controller is 3.08.00
with both `HomeServer` and `Studio-Native` connected and unpaused. TV Shows,
Anime TV and Indian TV now use `homeserver-hevc-offload-v2`, CRF 20 and
`/temp/studio-native`, with all schedule slots open. A real TV episode was
observed encoding on No-Face after the copied-media acceptance run. Remaining
operational checks are recorded in
[`TDARR-STUDIO.md`](../docker/docs/TDARR-STUDIO.md#open-checks-before-cutover).

**Deployment:** Dante requested committing and activating
the offload to reduce Calcifer's heat and fan activity. The corrected handoff is
packaged as `hevc-offload-v2.cjs` / `homeserver-hevc-offload-v2`, leaving the
older deployed v1 module and flow untouched. The deployment configuration now
seeds zero Linux CPU encoders, one GPU-type publisher, one CPU health-check
worker, and a four-CPU container quota. These settings were verified after
controller recreation. No-Face uses one CPU encoder with an x265 pool of nine
threads; it reported no thermal/performance warning during the observed run.

**Restart behavior (Dante):** automatically resume encoding after a node
restart. The installer now supports `--auto-resume` (opt-in; new installations
still start paused) and `--start-paused` to reverse it. The choice is stored in
`/var/lib/studio-worker/tdarr-start-paused`, written as `_studio` with mode 0600
and preserved by ordinary updates. It is now enabled and was verified after a
real node stop/start. Stop and disable the Mac daemon before rolling back to
Linux-only encoding.
The controller image is pinned to the deployed 3.08.00 digest so unattended
updates cannot advance it beyond the matching native node.

The matching 3.08.00 Apple Silicon node runs under `_studio`, with its
LaunchDaemon persistently enabled. The current installer and modules are staged
under the No-Face admin's `~/Services/tdarr-cutover-v2`; the earlier restore
package remains at `~/Services/tdarr-no-face-restore`. Both production copies
of `hevc-offload-v2.cjs` were verified by SHA-256
`ac44184bf5d3a9db03a4c14b2db1d9229a1280e6053d4ae6901324c7277a4bee`.
The older v1 module and flow were not overwritten. The root-owned helper
`/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-launcher` is the only
component granted Full Disk Access for Tdarr. The dedicated API key was
provisioned. The transfer daemon authenticates as `studio-tunnel` from `.80`;
the Mac's loopback endpoint reports the live controller healthy. Calcifer's
Nix generation installs the public key as a root-owned regular file because
OpenSSH `StrictModes` rejected the former symlink through `/nix/store`. The
restricted destinations are unchanged.

**Production-pair acceptance:** an accented-name disposable copy completed
the Mac encode, Linux private-copy validation/publication and independent full
decode (125 MiB H.264 to 96,755,901-byte HEVC; AAC/SubRip and 332.559 s
preserved). Its test-only CRF was 24; production remains 20. The Mac manifest
was 0600 with one link and its handover was cleaned. Three original staged
jobs survived more than six minutes while the single Mac CPU worker was paused.
An unchecked schedule also blocked staged pickup; reopening the canary schedule
resumed it. Two controller prepare/recreate/release cycles restored both nodes.
The clean Mac stop/start retained the FDA grant and automatically resumed.
The encode had already finished before that stop: mid-encode node loss,
dead-tunnel recovery and cold boot were **not** tested.

**Earlier isolated end-to-end canary:** the separate `tdarr-noface-test` controller,
`LabPublisher`, and `_tdarrtest` No-Face CPU node used only copied media and a
test-only no-op notification; no production queue, library, media, or
notification was involved. The first CRF 20 encode was larger than its source
and the 5% savings gate correctly retained the original. A second copied
sample encoded at test-only CRF 24 produced a 92 MiB HEVC file from a 125 MiB
H.264 source. The Linux leg copied it into private staging, validated and fully
decoded it, published it over the disposable copy, and the Tdarr job finished
with `Transcode success`. Audio, subtitle and duration were preserved; an
independent full decode passed. The original source checksum remained
unchanged. This validates the encode/return path, not a production cutover.

The larger CRF 20 result was recorded as `Not required`; a valid two-second
sample and an accented-name sample also took the `prepare` skip and were
recorded as `Not required`. No `tdarr-workDir2-*` directories remained in the
shared cache after these jobs.

The canary exposed a stale Tdarr work-file path after the Mac moved its result
to the shared handoff directory. The finish step now returns the original
library file object for the Linux leg; the report confirms Tdarr no longer
attempts its disabled unmapped-file download. The lab-only no-op notification
also had to return `args.inputFileObj`. After production activation, the isolated
controller/SMB containers and private network were removed. Dante stopped and
disabled `com.danteb.tdarr-noface-test` and unmounted its two shares; its
admin-owned SSH forward was closed. The hidden, non-login `_tdarrtest` account,
offline lab files and older source samples remain for inspection, with no
lab Tdarr worker or lab network running. The four `sample-crf24*` copies, two
temporary skip fixtures and stale failed-retry handover were removed. The older
`sample.mkv`, `sample-final.mkv` and `sample-retry.mkv` were left untouched.
The later three production-pair acceptance fixtures were also removed after
disabling their test library; its metadata and job reports remain.

**Intent:** fully migrate TV encoding from Calcifer to No-Face, keeping Calcifer
as Tdarr control plane and Linux validator/publisher. Preserve quality-first
software `libx265`; the flow and settings may change if a better implementation
meets that intent. Planned and announced production pauses/drains are acceptable.

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

**Historical implementation status (2026-11-14; superseded by the No-Face
restore above).**

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
  isolated lab passed a complete Mac encode and the Linux handoff. The
  installer and `start-tdarr.sh` were rewritten afterwards (a review found a
  symlink race in the root-run installer and a stall on dead mounts) while the
  Studio was unreachable after a power loss. Their mocked regression tests now
  pass on No-Face, but no live install or launchd operation was run; see the
  [remaining checks](../docker/docs/TDARR-STUDIO.md#studio-script-mocked-tests-live-checks).
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

**Earlier custom-tag attempt (not the installed offload flow):**

- Design (agent and a security reviewer): a native node as `_studio` reaches
  the server's controller through the SSH tunnel. The flow
  `homeserver-hevc-studio-v1` has Linux check the source, the Mac encode into a
  cache, then Linux validate and publish, so the Mac can never replace
  originals.
- **The controller/node split worked:** tunnel, registration and job delivery
  all functioned. **Production routing is blocked by two separate issues:**
  custom node-tag routing used by the flow requires Tdarr Pro and is ignored
  without a license; independently, Tdarr 3.07 applies library exclusions
  (`librariesToNotProcess`) only to fresh queue selection, not already-staged
  jobs, and untagged staged jobs match any node. The Mac previously took 23
  staged production TV jobs; each failed safely because it could not create
  Tdarr's `/temp/tdarr-workDir2-*` work folder. Nothing was encoded or
  replaced, and *Dante* chose to requeue the 23 jobs.
  [Incident details](../docker/docs/TDARR-STUDIO.md#free-tier-limits-and-the-2026-11-13-incident).
- An isolated follow-up lab required manually pausing nodes at each handoff;
  a tagged staged item resumed on Linux storage instead of the Studio. A
  full-episode encode took 39m18s and produced 582,779 KiB from a
  498,226,784-byte source, so Linux validation retained the original and its
  SHA-256 was unchanged. A 31-second excerpt padded from 11,687,533 to
  134,217,728 bytes passed private-copy validation, full decode and publication,
  but its apparent savings are not representative. Filesystem/network
  isolation denied an eligible decoy, but a separate queued/staged-decoy
  scheduler test was not performed. This is not production-ready evidence.
- The production Studio Tdarr daemon remains disabled. No production service,
  library or queue changed in the lab. Its server containers, networks, copied
  media/cache/state and temporary SSH forward were removed; production mounts
  remain. After explicit authorization, cleanup removed the three booted-out
  lab plists and two lab directories/logs listed under [On the Studio](#on-the-studio).
  Preflight found only regular files/directories (no symlinks or special
  files); all five targets were absent on post-check, no lab Tdarr process
  remained, production SMB mounts remained mounted, and production Tdarr
  services remained running.

**Next:** monitor the production offload and work through the remaining
operational checks. For changes, use the
[cutover and rollback runbook](../docker/docs/TDARR-STUDIO.md#cutover-and-rollback).
The worker-type design replaces the unsupported custom-tag attempt;
agents may replace its mechanisms with a simpler implementation that meets
Dante's intent.

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
| `macos/install/` | `install-tdarr-node.sh` installs or updates the Studio's Tdarr node and is safe to rerun: it checks and builds everything before replacing anything, builds the launcher only when missing, and has the worker write its own files, so root never writes inside the worker's tree (Linux-tested only so far). The other installers are historical one-time scripts from 2026-11-13, not ready-to-rerun provisioning: their staging inputs and comparison models were removed; reusable sources are in `macos/` and `macos/ai/` |
| `macos/checks/` | Isolation checks: worker boundaries, share access, Tdarr node authentication |
| `macos/install/install-tailscale.sh` | Tailscale installer (`wake` has its own installer in [dantebarbieri/wake](https://github.com/dantebarbieri/wake)) |
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
| Maintenance forwarding account | `_arrmaint`, `/etc/ssh/sshd_config.d/003-arr-maint-forwarding.conf`, `/etc/ssh/arr-maint-forwarding-keys`, membership in `com.apple.access_ssh` | [Transport removal](ai/README.md#ollama-transport) |
| Tailscale | `com.tailscale.tailscaled`, `/usr/local/bin/tailscaled`, state in `/Library/Tailscale/`; Homebrew `tailscale` | `sudo tailscale logout`, `sudo tailscaled uninstall-system-daemon`, `brew uninstall tailscale`, delete the machine in the admin console |
| wake | `/usr/local/bin/wake`, `com.danteb.wake-update` (`/Library/LaunchDaemons/com.danteb.wake-update.plist`), `/var/log/wake-update.log` | `curl -fsSL https://raw.githubusercontent.com/dantebarbieri/wake/main/install/install.sh \| sudo sh -s -- --uninstall` |
| Tunnel and mounts | `com.danteb.studio-transfer`; mounts under `/private/var/lib/studio-worker/mounts/` | Unmount, `bootout`, delete the plist |
| Native Tdarr node (installed, paused until the cutover) | `com.danteb.studio-tdarr` (plist in `/Library/LaunchDaemons`), the launcher and session script `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-{launcher,session}`, `/var/log/studio-tdarr`, worker `tdarr/` (node, `Custom/` modules and any `Custom.superseded.*` the installer moved aside), the launcher's Full Disk Access entry in System Settings | `sudo bash macos/install/install-tdarr-node.sh --stop` boots it out, disables it, waits up to a minute for the node, its encoders and any share probe to exit and lists whatever is left (exit 3). To remove it, delete those files (`Custom.superseded.*` is root-owned and needs `sudo`) and the launcher's Full Disk Access entry; optionally `sudo launchctl enable system/com.danteb.studio-tdarr` to clear the disabled flag |
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
| Bazarr's Whisper link | `studio-whisper` container; key and pinned Studio host key in `/srv/docker/data/studio-whisper-tunnel`; Bazarr's `whisperai` endpoint and timeout | Restore the `whisperasr` service to `compose.ai.yml` from git (last present in `66fa2ee`), point Bazarr back at it, then [remove the transport](ai/README.md#bazarr-transport-and-cutover) |
| Bazarr migration rollback/evidence | `/srv/docker/data/bazarr/config/studio-migration-20261113/`: pre-cutover config and SQLite backup, aggregate `smoke-result.json`; original image tagged `bazarr-before-studio:20261113` | Backups contain secrets; keep private. Endpoint rollback normally needs only the settings change, not database restoration |
| Tdarr | Active `Studio-Native` node and `homeserver-hevc-offload-v2` on the three TV libraries; disabled canary libraries; versioned worker modules in `Custom/`, dedicated API key, snapshots in `/srv/docker/data/tdarr/server/Tdarr/Custom/backups/` (mode 0600; may hold credentials) | Follow the guarded rollback runbook, stop the auto-resuming Mac daemon, then delete the node, canary libraries and flows in the UI and revoke the key |
| AdGuard | Two `home.arpa` rewrites | AdGuard UI, DNS rewrites |

## Open items

1. Cold-boot test, including the FileVault pre-boot SSH unlock, then check
   Ollama, Whisper and `tailscaled` come back on their own. The unplanned
   2026-11-14 power loss was the first real one; record the unlock procedure
   (see [Headless](#headless-and-back-on-its-own-after-power-loss)).
2. Prune retired SSH keys on the Studio (and the server if retired there too).
3. Use `home.arpa` for future service integrations. Admin SSH migration is
   complete on the reachable hosts; the MacBook is intentionally unchanged.
4. Speech: Bazarr's cutover is complete
   ([details](ai/README.md#bazarr-transport-and-cutover)) and the server's
   `whisperasr` has been removed. English remains a proofread
   fallback; Japanese and Telugu still need audio-grounded review, not more
   overlap scoring.
5. Ollama: pick a first automation, or remove it.
6. Tdarr: finish the remaining canary checks, then cut the TV libraries over
   and settle the Studio's worker count and x265 `pools`
   ([runbook](../docker/docs/TDARR-STUDIO.md#cutover-and-rollback)). Decide
   whether to secure the Studio's power (a UPS) or keep FileVault, since an
   unplanned power loss now stops the offload until someone unlocks the disk.
7. After the next NixOS activation, check the server's sshd file is the Nix
   symlink and reconcile the private transfer Compose overlay with
   `compose.studio.yml`. The Bazarr migration does not rebuild NixOS or
   change the Tdarr transfer setup.
