# Mac Studio and server cooling: decision and cleanup log

State as of 2026-11-13, branch `dantebarbieri-server-cooling` (not pushed, no PR).
This covers one long Copilot session: server overheating and hardware inventory,
then the headless Mac Studio (`ai-studio`) setup and the native Tdarr attempt.
Operational details live in [`macos/README.md`](../macos/README.md),
[`macos/ai/`](../macos/ai/README.md) and [`docker/docs/TDARR.md`](../docker/docs/TDARR.md);
this file records **what was done, why, who chose it, and how to undo it**.

## Read this first: this work is replaceable

Dante's requests were basic: set up the Mac headless, secure SSH, install Whisper,
make it a Tdarr node, get Docker, use local DNS names. The agent turned several of
them into far more specific designs. Dante's standing instruction:

> "If in the future, an agent can better solve one of my requests, it should be
> allowed to clean up your work without feeling like I had my heart set on doing
> it that specific way."

- Only rows marked **User** record a choice Dante actually made. **Agent** rows are
  Copilot defaults; **Reviewer** rows were required by the separate Server security
  review session. Agent and Reviewer choices may be simplified, replaced or removed.
- Prefer removing old pieces over layering new ones on top. Removal steps are in
  [Live state and how to remove it](#live-state-and-how-to-remove-it).
- Dante wants to review this and propose alternatives. Update this file when the
  setup changes instead of starting another log.

### Hazards any replacement must still handle

These are facts, not preferences:

- **Tdarr 3.07 staged jobs ignore node exclusions.** `librariesToNotProcess` is only
  applied to fresh queue selection; untagged staged jobs match any node. Any extra
  node on the shared controller can receive old production work. Tags and
  exclusion readback are not proof of isolation (see [incident](#9-tdarr-canary-incident-and-recovery)).
- Production originals must only be replaced by the validated production flow.
- Tdarr reports and node configs can contain credentials; never print or commit them.
- Never run `docker compose -f compose.<category>.yml up` on the server.
- Assume router setting changes reboot the router.

## Original requests (paraphrased)

1. Fans surge every few seconds, worst during Whisper subtitling. Get server and BMC
   inventory, review a fan video and the build spreadsheet. Is better cooling needed?
   Which HDDs to buy at Micro Center?
2. Real disk count from mdadm/LVM. Are disks missing? Would reconnecting rebuild?
3. Would a Mac Mini/Studio for Whisper, services and local AI reduce server load and heat?
4. Motherboard manual and an interactive pin/fan map. Later: go through each
   component to remove diagram uncertainties and link manuals.
5. Set up the new Mac Studio headless. Reuse the server's SSH keys ("most
   convenient"). Pin a DHCP lease.
6. Disable SSH passwords and root login; Homebrew, zsh, Zim, fastfetch, other setup.
7. Install Whisper, make it a Tdarr node, get Docker ready for services that could
   move, and resolve the Mac through AdGuard local DNS.
8. Rebuild the Tdarr node natively; Dante cares about the result, not the config.
9. Local models that could later add judgement to maintenance automations.
10. This log.

## Current state at a glance

| Area | State |
|---|---|
| Server cooling | Six Noctua fans on a hub at FAN3. Fan-surge cause not conclusively diagnosed |
| RAID | md0 RAID6, 11 active + 1 hot spare, healthy after a SATA power fix |
| Mac administration | Key-only SSH, Homebrew, zsh/Zim/fastfetch |
| Local DNS | `ai-studio.home.arpa`, `homeserver.home.arpa` in AdGuard |
| Colima | Running and idle; no services moved |
| Mac Whisper | Running on Mac loopback `:9000`; **Bazarr still uses the server's Whisper** |
| Ollama | Running on Mac loopback `:11434`; nothing uses it |
| SSH tunnel, SMB and relays | Running; media mounted read-only and cache read-write on the Mac, idle |
| Native Tdarr | **Disabled and blocked** after the staged-job incident |
| Server Atlas map | Separate unmerged branch |

## 1. Overheating, inventory and RAID

The agent did read-only SSH, BMC, Prometheus, SMART, SEL and video review. No server
or BMC configuration was changed by this investigation.

**Facts found**

- AMD EPYC 7313P, ASRock Rack ROMED8-2T rev 1.03, 128 GB RAM, Corsair HX1000i,
  Rosewill RSV-L4500U. GPU in PCIE3, HBA in PCIE1 directly under the GPU intake.
- The RTX 2070 SUPER is intentional: the EPYC would not POST with the RTX 3060 (**User**).
- Two Samsung 990 EVO 2 TB NVMe without heatsinks under the GPU overhang.
- 12 × WD80EFPX 8 TB. RAID6 has distributed parity, not parity disks: 11 active plus
  1 hot spare is complete. The four extra spreadsheet drives were never members.
  The BMC does not inventory HDDs. `/data` is XFS on LVM, ~66 TB, ~81 % used then.
- Historical peaks: CPU Tctl 85.5 °C, an NVMe sensor ~106 °C, HDDs 47–51 °C,
  repeated BMC 55 °C motherboard warnings. The sustained load at the time was four
  CPU Tdarr encoders, not Whisper.

| Decision | Chosen | Why | By | Simpler / alternative |
|---|---|---|---|---|
| First response | Clean, give the closet clearance, then add controllable fans | Evidence pointed to airflow plus sustained CPU encoding, not a failing part | Agent advice; **User** cleaned and moved the server | Only cap Tdarr concurrency |
| Fans | Six Noctua NF-P12 redux-1700 PWM on a Thermalright ARGB 8-group hub at FAN3 | Molex fans cannot be controlled or monitored | **User** bought and installed (agent had suggested a SilverStone CPF04 hub) | — |
| HDDs | No new drives | Only three free bays; 12 is the intended count | **User** | — |
| Encoding | Keep CPU `libx265` quality-first | Hardware encoders are not equivalent quality per byte | **User** goal | NVENC/VideoToolbox for speed |
| Offload computer | Mac Studio M5 Max 36 GB (MHL64LL/A, $1,999.99) | More CPU/GPU and bandwidth than the 48 GB M4 Pro mini for +$300 | **User** after agent comparison | 48 GB Mac mini |

After the fan install six drives lost SATA power and the server entered emergency
mode. The agent advised against mdadm or XFS repair; Dante reseated the power cable
and the array and `/data` returned intact.

## 2. Server Atlas (hardware map)

Branch `dantebarbieri-server-hardware-map` (child worktree
`dantebarbieri-super-broccoli`): a static `hardware-map/` app with model tests,
commits `276c1d6` … `75f0eaf`. Not merged, no PR, not deployed. The vendor manual's
artwork is deliberately not committed; facts are marked verified, inferred or unknown.

- **User:** asked for the map, then landscape layout, less clutter, dismissible popups.
- **Agent:** schematic style, provenance states, the app architecture.
- **Simpler alternative:** a Markdown inventory table with manual links. The
  component-by-component walkthrough Dante asked for has **not happened yet**.

## 3. Mac Studio headless basics and SSH

| Decision | Chosen | Why | By | Simpler / alternative |
|---|---|---|---|---|
| Remote access | Screen Sharing and Remote Login (SSH) | Built in; tested from the MacBook | **User** enabled | Remote Management (ARD) is not needed |
| Address | Router DHCP reservation `192.168.50.140` (Ethernet) | Stable SSH target | **User** | DNS names only |
| Mac `authorized_keys` | The server's seven declared public keys, unpruned | Dante asked for the same set | **User** | Prune the `WorkPC` and retired `DESKTOP-DD5K2PO` keys (agent recommends) |
| Host-to-host access | New per-host keys: Mac `~/.ssh/id_ed25519` → server (`ssh homeserver`); server `~/.ssh/id_ed25519_studio` → Mac (`ssh studio`). Passphrase-less, `from="192.168.50.0/24"` | Private keys are never copied between machines | Agent | Dante's idea: only reach the Mac via the server; or one key with an agent |
| Mac sshd | `/etc/ssh/sshd_config.d/000-studio-hardening.conf`: no root, public key only | Requested hardening; macOS uses the first value read | **User** asked; Agent settings | — |
| sudo | `dante` is in macOS `admin`, which grants sudo (macOS does not use `wheel` for this) | Fact | — | — |
| Shell | Homebrew + CLT, zsh, Zim matching the server modules and asciiship prompt, zoxide, bat; fastfetch only on interactive TTY logins | Match other devices; keep scripted SSH/SFTP clean | **User** asked; Agent details | — |
| Power | `autorestart 0` (unchanged) | Needs Dante's sudo | Open | `sudo pmset -a autorestart 1` |

The Studio's admin public key is in the server's live `~/.ssh/authorized_keys` and
also declared in `nixos/modules/users.nix` on this branch (not yet activated).
FileVault is on: after a power loss the data volume must be unlocked before any
service starts. No reboot test has been done.

**Windows PC:** `hosts` maps `ai-studio` to `192.168.50.140` (previous copy in the
session folder as `ai-studio-hosts.before`). `~/.ssh/config` has `Host ai-studio`
with `id_ed25519` and `HostKeyAlias ai-studio`. A child session moved fastfetch out
of the Windows Terminal command line into a guarded
`Documents\PowerShell\Microsoft.PowerShell_profile.ps1`; the old settings are in
`settings.json.before-pwsh-startup-fix-20261113-050214.bak` in the Terminal
`LocalState` folder.

## 4. Local DNS

| Decision | Chosen | Why | By | Simpler / alternative |
|---|---|---|---|---|
| Names | AdGuard rewrites `ai-studio.home.arpa` → `.140`, `homeserver.home.arpa` → `.100`, added through the API without restarting AdGuard | Avoid scattering IPs; `home.arpa` is reserved for home networks | **User** wanted local DNS; Agent chose names | Router DHCP hostnames |
| Mac resolver | `/etc/resolver/home.arpa` → `192.168.50.100` | Private names never leak to fallback DNS | Agent | Rely on DHCP DNS |

Not done: SSH aliases on all three machines still use IPs, not these names.

## 5. Docker on the Mac (Colima)

- **User:** Colima instead of Docker Desktop.
- **Agent:** system LaunchDaemon `com.danteb.colima` running as `dante`; ARM64 VZ VM
  with 4 CPU, 6 GiB, 60 GiB disk; only `~/Services/docker-shared` mounted; no TCP
  listener. Scope: keep storage, databases, *arr apps, DNS, NPM, auth and the Tdarr
  controller on the server; offload only Whisper and CPU encoding first.
- Nothing runs in it. **Simpler alternative:** remove Colima until a service is
  actually chosen to move.

## 6. Speech and local AI

| Decision | Chosen | Why | By | Simpler / alternative |
|---|---|---|---|---|
| Whisper runtime | Native `mlx-whisper` 0.4.3, large-v3, LaunchDaemon `com.danteb.studio-whisper` as `_studio` on loopback `:9000` | MLX needs macOS Metal, unavailable inside Colima's Linux VM | Agent | Same model as `dante`, reachable from Bazarr |
| Evaluation | Real English, Japanese and Telugu episodes | Model claims are not media-specific quality | **User** ("try all 3") | Just copy the server's model |
| English decoding | `condition_on_previous_text=False` only for English transcription | English cue overlap 527→623/630, no punctuation loops | Agent from benchmarks | — |
| Not global | Default kept for other languages | It hurt Japanese (304→285/309) and Telugu (313→301/319) | Agent | — |
| Other models | Qwen3-ASR not adopted; Parakeet and SeamlessM4T rejected | Lower overlap, language gaps, licensing | Agent | — |
| Local LLM | Ollama `qwen3:8b`, loopback `:11434`, one model; no Open WebUI | Baseline for structured advisory output | Agent (Dante asked for models, not this one) | Remove, or try MLX/llama.cpp |

Overlap counts measure timing coverage, not accuracy. **Bazarr has not been moved**:
semantic quality is unproven, the provider patch in `macos/ai/` is undeployed, and
there is no transport from Bazarr to the Mac's loopback service.

## 7. Worker isolation and private transport

This is the largest elaboration beyond the requests.

- Mac `_studio` (UID 499, home `/var/lib/studio-worker`, no shell, SSH denied via
  `/etc/ssh/sshd_config.d/001-studio-worker.conf`) runs Whisper, Ollama, the tunnel
  and Tdarr. Homebrew tools get read/execute ACLs from `macos/allow-worker-tools.sh`.
- Linux `studio-tunnel` (UID 993, nologin) uses keys in
  `/etc/ssh/studio-transfer-keys` and may only forward to `127.0.0.1:1445` and `:8266`.
- `studio-media-share` (Samba): media read-only, cache
  `/tmp/tdarr_transcode_cache/studio-native` writable, SMB3 signing, no symlinks.
- `studio-transfer-relay` (`:1445`) and `studio-tdarr-relay` (`:8266`): unprivileged
  socat, server loopback only.
- Mac `com.danteb.studio-transfer` keeps the SSH tunnel up. `mount-studio-share.c`
  mounts through NetFS; the root launcher
  `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-session` selects the
  worker audit session and drops to `_studio`.

**Why:** Tdarr and FFmpeg parse untrusted media. The design keeps a compromised
worker away from admin keys, Docker, original media writes and other server
services, and adds no LAN, WAN, router or NPM exposure.

**User chose:** "SSH-protected media share" over Tdarr Pro or unmapped transfer;
the private 8266 SSH forward; account isolation plus Samba restrictions; the
restricted launcher. **Everything else is Agent or Reviewer.**

**Simpler alternatives**

- Tdarr Pro unmapped node: no shares, tunnel, relays or NetFS helper; costs money.
- Read-only LAN SMB/NFS export restricted to the Mac's IP, Tdarr as an ordinary user.
- Skip Mac encoding; schedule or cap server Tdarr workers to control heat.
- If Mac Tdarr is abandoned, remove this whole section's pieces.

## 8. Native Tdarr design

- **User:** rebuild natively; result over configuration.
- **Agent/Reviewer:** three-stage storage-authoritative flow
  `homeserver-hevc-studio-v1` (Linux checks identity → Mac encodes `libx265` slow
  into the cache → Linux validates and atomically publishes), so the Mac can never
  replace originals. Forced Matroska probing of returned output (fix approved by
  **User**). Canary library `homeserver-hevc-studio-canary-v1`, one copied Frasier
  episode, CRF 20 (**User** approved the copied-media canary and froze libraries).
- **User** created the dedicated Tdarr API key in the UI; it was entered privately.
- The node uses `127.0.0.1:8266` through the tunnel. `tdarr.danteb.com` is port 8265
  and gives `Invalid namespace` to nodes.

## 9. Tdarr canary incident and recovery

Despite a paused node, a `studio-native` tag and verified exclusions, the Mac took
**23 staged production TV Shows jobs**. Each failed creating a work directory on the
read-only `/temp`. No encode or publication happened. Sizes and timestamps of all 23
sources matched and predate the attempt; there were no prior hashes, so this is
metadata evidence. Cause: the staged-job path described under
[hazards](#hazards-any-replacement-must-still-handle).

Recovery: daemon booted out and disabled; HomeServer node tags restored to `mapped`;
settings checked against the pre-canary snapshot; **User** chose to requeue only the
23 jobs (only their `TranscodeDecisionMaker` field changed). Production Tdarr was not
restarted. Commit `f94ec60` documents it and blocks activation.

**Native Tdarr stays off** until Dante approves one of: a separate canary-only
controller with a dedicated worker and disposable media; a verified upstream fix for
both fresh and staged selection; or abandoning Mac encoding. Any option needs a
negative test with an eligible disposable decoy. Do not drain or retag shared
staging or globally pause production as a workaround.

## Live state and how to remove it

### Mac Studio

| Item | Location | Remove |
|---|---|---|
| Native Tdarr (disabled) | `/Library/LaunchDaemons/com.danteb.studio-tdarr.plist`, `/Library/PrivilegedHelperTools/com.danteb.studio-tdarr-session`, `/var/log/studio-tdarr`, worker `tdarr/` | Delete the files; optionally clear the leftover flag with `sudo launchctl enable system/com.danteb.studio-tdarr` |
| Leftover staging | `~/Services/tdarr` (400 MB), `~/Services/ai-staging` (1.3 GB) | Delete once unneeded |
| Tunnel and mounts | `com.danteb.studio-transfer`; mounts under `/private/var/lib/studio-worker/mounts/` | Unmount, `sudo launchctl bootout system/com.danteb.studio-transfer`, delete plist |
| Whisper, Ollama | `com.danteb.studio-whisper`, `com.danteb.studio-ollama` | `bootout`, delete plists and worker data |
| Colima | `com.danteb.colima`; Homebrew `colima docker docker-compose docker-buildx` | `bootout`, `colima delete`, `brew uninstall` |
| Worker account | `_studio`, `/var/lib/studio-worker`, `001-studio-worker.conf`, ACLs from `allow-worker-tools.sh` | Last: remove ACLs (`ls -le`), `sudo dscl . -delete /Users/_studio`, delete home and conf |
| Admin setup | `000-studio-hardening.conf`, `/etc/resolver/home.arpa`, dotfiles, `~/.ssh` keys | Keep unless replacing |

### Homeserver

| Item | Location | Remove |
|---|---|---|
| Relays and Samba | `studio-media-share`, `studio-transfer-relay`, `studio-tdarr-relay`; Compose project `compose` with private overlay `/srv/docker/data/studio-transfer/compose.studio.yml` (branch copy: `docker/compose.studio.yml`, `studio-transfer` profile) | `docker rm -f` the three, remove their networks, delete `/srv/docker/data/studio-transfer` (holds `samba.env` secret) and the cache dir |
| sshd | `/etc/ssh/sshd_config` is a root-owned file shadowing the Nix symlink, plus a `studio-tunnel` Match block; backups in `/var/backups/studio-transfer/` | Restore the Nix symlink from backup and reload sshd. A NixOS activation from `main` may do this too, which breaks the tunnel (fails closed) |
| Tunnel account | `studio-tunnel`, `/etc/ssh/studio-transfer-keys` | `userdel`, delete file, drop it from `users.nix`/`ssh.nix` |
| Studio admin key | `~/.ssh/authorized_keys` and `users.nix` | Delete the line |
| Tdarr | `Studio-Native` node record, canary library and flow, dedicated API key, helpers and private backups in `/app/server/Tdarr/Custom/` | Delete in the UI; revoke the key; backups may hold credentials |
| AdGuard | Two `home.arpa` rewrites | AdGuard UI → DNS rewrites |

Production Compose updates (`up -d`) leave the overlay containers running;
`--remove-orphans` from the main file would remove them.

## Commits

On `dantebarbieri-server-cooling`: `af77492` native AI setup · `c909710` speech
comparison · `d54933b` storage-authoritative Tdarr flow · `3e3bf06` experimental
Whisper API · `351ff5e` Tdarr 3.07 support · `5910f78` English decoding ·
`9978ec3` English recheck docs · `17e6da0` forced Matroska · `58ee46b` canonical
macOS paths · `6266647` isolated workers and transport · `f94ec60` activation block
and incident · this log.

## Private records (not in git)

- Copilot session `d6730317-3dba-429c-a07c-2f50a97c4938` on Dante's Windows PC
  (`%USERPROFILE%\.copilot\session-state\…\files`): photos, the board manual PDF,
  thermal history, provisioning and recovery scripts. `start-studio-canary.cjs` now
  throws; do not rerun `recover-studio-canary-errors.cjs`.
- Related sessions: Server security `b2774865…`, Studio AI `6cab1426…`, Studio Tdarr
  `18549a92…`, Windows profile `62d0a882…`, Server Atlas `d55dd5d3…`.
- Tdarr snapshots `studio-live-canary-*`, `studio-canary-impact-*`,
  `studio-canary-recovery-*` in `/app/server/Tdarr/Custom/backups/` (mode 0600).

## Open items

1. Walk through the hardware with Dante; resolve Atlas unknowns and link manuals.
2. Find the fan-surge cause under real load (BMC sensor source and fan curve).
3. NVMe heat: one sensor ~78 °C under boot I/O; measure clearance before buying a heatsink.
4. Rear 80 mm fans are still Molex; FAN4–7 and the HDD power harness are unverified.
5. Mac: `pmset autorestart`, FileVault cold-boot test, prune old SSH keys, use
   `home.arpa` names in SSH aliases.
6. Decide native Tdarr's future (section 9). While blocked, consider stopping the
   tunnel, mounts and relays.
7. Bazarr cutover to Mac Whisper, or decide not to.
8. Ollama has no consumer; keep or remove.
9. Push and PR this branch; reconcile the sshd shadow and Compose overlay with Nix
   and `main`. Merge or drop the Atlas branch.
