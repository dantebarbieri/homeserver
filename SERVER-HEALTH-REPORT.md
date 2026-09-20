# Server health audit - 2026-09-19

## September 20 maintenance follow-up

The owner authorized host maintenance and a reboot, while deferring the
container-specific findings. Host-only changes were committed as `3ec4e5a`,
pushed to `main`, pulled on production, and built with `nixos-rebuild boot`.
The existing media/Tdarr changes through `a275dff` were preserved.

Terminal mail/calendar integration was **retired**, rather than repaired:
aerc, khard, khal, vdirsyncer and w3m are absent from the new system profile,
the login calendar is removed, and the sync service/timer no longer exist.
Stored data, credentials, the general-purpose password store, and optional
portable templates were preserved.

The authorized reboot was initiated at 07:42 CDT; SSH returned by 07:50.
The running and booted generations now match. Kernel **6.18.52** and NVIDIA
module/userspace **595.99.02** are active, and `nvidia-smi` succeeds.
Both bond members report 10 Gb/s, full duplex, up, with zero link failures;
**enp66s0f1 is now both primary and active**. IPv4, the stable IPv6 GUA, and
default routes are unchanged. No router settings or destructive failover
test were used.

The old parity check was deliberately stopped before reboot, without being
reported as complete. A **fresh full check started at 07:51**, with all 11 RAID
members present and the spare available. At 07:52, a controlled monitor restart
left the kernel check running; the replacement monitor logged
`Monitoring existing parity check on /dev/md0`, restored its runtime sentinel,
and continued observing advancing progress. The intentional termination also
triggered the configured failure notification. Full parity completion remains
pending; a zero mismatch count so far is not a completed scrub result.

The host updater now serializes itself, keeps Git maintenance in the foreground,
uses fast-forward-only pulls, limits image pulls to four concurrent Compose
operations, and retries failed pulls at most three times (60/120-second waits).
Persistent failures stop before build/deployment and notify through ntfy.
The live full update ran from **07:51:29 to 07:57:42** and finished with
`Result=success`, `ExecMainStatus=0`. Pull, build, reconciliation and the existing
image/network cleanup sequence completed; no pull retry was needed on this run.
The standard image cleanup reclaimed 20.14 GB. This demonstrates a successful
run with the new pipeline, not a guarantee that registries never throttle again.

The actual Plex hardware-acceleration probe also passed at **07:58:04**.
Whisper, initially stopped after boot, was restored to running by the normal
update reconciliation. No failed host units remained at the final check.

**Container follow-up still needed:** 92 containers were running, while Hytale
was restarting. Its startup downloader reports an expired OAuth refresh token
(`invalid_grant`). The errors began after reboot and before the update job;
an image rollback cannot renew that token. No credentials were deleted or
changed, and interactive Hytale reauthorization is deferred to the container
work rather than folded into this host-only rollout.

Local option evaluation, the complete Linux system derivation, and mocked
update/scrub error-path checks passed against the September 20 channel revision
`20b1ddd1aa5ace70c9468305030aa4f9ef79671b`. The actual server build succeeded.

The proposed socket-consumer helper is **not enabled in this host rollout**.
Deferred container work is preserved in local Git stash
`3139826e5eabb87031d8d05e605c94d619bb1132` ("Deferred container findings from
server health audit"). Recyclarr example URLs were independently corrected
upstream before this rollout; preserve those upstream changes when revisiting
the stash. Application-specific findings will be reassessed later.

**The remainder is the original September 19 audit snapshot.** Its
no-production-changes statement and sync/socket proposals describe that earlier
read-only phase and are superseded by this follow-up where noted.

**Main result:** four high-priority operational problems warrant attention:
NVIDIA driver version drift, seven consecutive failed daily container updates,
continuous contact/calendar sync failures, and stale Docker socket mounts that
break monitoring and VPN recovery. The RAID is not degraded and storage/RAM
capacity is not an immediate emergency; this does not call for blind pruning,
driver replacement, or reinstalling the server.

Evidence-backed prevention/isolation changes are prepared locally. Existing
driver/socket failures still need an approved maintenance rollout, while Google
authorization and private application configuration require separate repairs.

## Scope and safety

Read-only inspection through `ssh server`, starting at 21:00 CDT on September
19, 2026. The host review covered the preceding seven days of service errors,
selected boot/kernel warnings, running drivers, networking, storage, timers,
and backup job status. This is an operational/configuration audit, not a
penetration test or an exhaustive application/backup restore test.

**No fixes were applied to production.** No reboot, service restart, rebuild,
container deployment, synchronization, credential change, or cleanup/prune was
performed. Changes in this worktree are proposals for review. They have not
been pushed or merged, so the server's daily Git pull cannot pick them up.
Credentials and private calendar/media identifiers are intentionally omitted.

Production's checkout was clean at `a94a6d06b890812b093634ba7abfd51238aafd6b`,
matching the local starting point. The host had been up for almost 49 days.

## Prioritized host findings

| Priority | Finding | Evidence | Proposed disposition |
|---|---|---|---|
| High | NVIDIA kernel/userspace mismatch | `nvidia-smi` fails with `Driver/library version mismatch`; loaded module **595.84**, userspace **595.99.02**. Running kernel **6.18.41**, current system profile contains **6.18.52**. | Local change stages automatic OS updates for the next boot. A separately approved maintenance reboot is still needed to reconcile the existing mismatch. |
| High | Daily container updates failed on all seven reviewed days | September 13-17 and 19: `chown` races a disappearing `.git/objects/maintenance.lock`; September 18: GHCR returns `toomanyrequests` and the pull aborts. | Local change runs Git's automatic maintenance synchronously before ownership repair and adds failure notification. Registry throttling remains an external failure mode. |
| High | Contact/calendar sync fails every 15 minutes | **672 failed invocations** in seven days, no successful whole-job completion in that window. Google reports `(invalid_grant) Bad Request`; other collections also report `Server disconnected`. | Local change isolates configured pairs in separate processes and retains a failing exit status. Google reauthorization remains a manual requirement; iCloud must be checked separately afterward. |
| Medium | Weekly scrub monitor was killed during OS activation | September 13 at 04:32:08: scrub service receives SIGTERM. Restart at 04:32:16 fails writing `check` with `Device or resource busy`. | Local change prevents definition-change restarts of an active scrub monitor and adds failure notification. No parity repair or new scrub was started. |
| Medium | Configured preferred bond member is ineffective | `/proc/net/bonding/bond0` says `Primary Slave: None`, active member `enp66s0f0`, despite configured preference for `enp66s0f1`. Generated networkd files lack `PrimarySlave`. | Local change uses networkd's `PrimarySlave=true` on `40-enp66s0f1`. Apply only in a maintenance window; selecting the preferred member may switch the live link. |

### NVIDIA and automatic OS activation

`system.autoUpgrade.allowReboot = false` does not mean "build only." The
installed module defaults `operation` to `"switch"`, and the deployed upgrade
script explicitly runs `nixos-rebuild switch --no-build-output --upgrade`.
That switches driver userspace while the old NVIDIA module remains loaded.
The existing `restartIfChanged = false` settings for NVIDIA services avoid
some restart failures but cannot make mismatched driver versions compatible.

The proposed `operation = "boot"` selects the new generation for the next boot
without live-switching the running system. **This also defers OS security fixes
until a planned reboot**, so regular maintenance reboots become part of the
update policy. It does not repair the currently loaded driver.

The existing Plex acceleration check reported success at 19:24 on the audit
day. Therefore this finding does **not** establish that every running
GPU-enabled container has lost acceleration: existing CDI mounts can retain
older libraries. Host NVML is demonstrably broken, however, and new workloads
or recreated services can behave differently. Do not unload NVIDIA modules
under active workloads as an improvised repair.

### Update failures are easy to miss

At inspection time `systemctl --failed` showed only vdirsyncer. The Docker
update service nevertheless retained `ExecMainStatus=1`, and its journal showed
seven consecutive failed scheduled runs. The current `Result=success` value is
not a sufficient historical health check after subsequent system activations.

The local fix sets both `maintenance.autoDetach=false` and
`gc.autoDetach=false` for the update's Git invocation. Git housekeeping still
runs, but must finish before the subsequent recursive ownership repair. Errors
are not hidden with `|| true`; a failed pull, ownership repair, or image pull
still prevents deployment. The existing ntfy failure handler is now connected
to this unit.

The September 18 rate-limit failure is not evidence of invalid Compose YAML.
No registry credential changes, unbounded retries, image downgrades, or
partial-deployment fallback were added.

### Calendar authentication and isolation

The Google `invalid_grant` response is confirmed; its exact cause (revoked or
expired refresh token, OAuth app policy, or another authorization issue) is
not established. Do not replace it with an app password or assume that retrying
will repair authorization.

The current command synchronizes all three pairs in one vdirsyncer 0.20.0
process. Its implementation shares an aiohttp connector and gathers concurrent
tasks. The repeated `Server disconnected` messages may be secondary failures;
without an isolated run it is not safe to declare iCloud credentials invalid.
The local change runs all pairs separately, logs their outcomes, and returns
failure if any pair fails. It neither disables Google nor claims to repair
authentication.

Interactive reauthorization and a controlled per-pair sync are deferred.
No credential files, tokens, calendars, contacts, or sync state were changed;
even an ordinary live sync would violate this audit's read-only scope.

### Scrub continuity

Stopping the systemd monitor does not stop the kernel's ongoing parity check.
Restarting the service blindly attempts a second `check`, causing the observed
busy error and losing the monitor/suppression sentinel for the original check.
The staged-update policy avoids scheduled live switches, and the explicit
`restartIfChanged = false` also protects against manual definition-change
switches while a scrub is active.

At inspection the array was clean, `sync_action=idle`, and `mismatch_cnt=0`.
These are reassuring current values, **not proof that the interrupted
monitor delivered its completion notification**. No automatic `repair` is
warranted by this evidence.

## Container findings

The bounded Docker review covered container states, filtered inspect fields,
recent logs (generally up to 400 lines per container over 24 hours), selected
seven-day follow-ups, and read-only socket/HTTP diagnostics. Production's main
Compose configuration passes validation.

| Priority | Finding | Evidence | Disposition |
|---|---|---|---|
| High | Four consumers retain obsolete Docker socket mounts | Host socket inode **25682644**; Homepage, Alloy and VPN watcher **17063585**; cAdvisor **10268**. Docker started September 16 at 04:31 CDT, after these containers. | Local lifecycle reconciliation is proposed; existing containers were not recreated. |
| Medium | Recyclarr daily sync is broken | All seven sampled daily runs, September 13-19 at 05:00 UTC, fail because `sonarr_url` is missing from `secrets.yml`. | Correct the production secret keys separately. Local example URLs now use service DNS instead of `localhost`. |
| Medium | qbit-manage share-limit configuration is invalid | 16 errors in the sampled recent log: group `noHL` has `min_seeding_time=20160` but unset `max_ratio=-1.0`. Runs still finish. | Review the persisted group configuration deliberately; no ratio was invented and intentional dry-run remains enabled. |
| Medium | AdGuard's Quad9 DoH upstream intermittently fails | 133 `unexpected EOF` errors in 24 hours against `dns10.quad9.net:443/dns-query`. | Investigate upstream/network behavior; not proof of total DNS failure. No resolver configuration was changed. |
| Medium | A Tdarr custom plugin has an invalid FFmpeg path | Recent `DV5 sidecar: FFmpeg path must be absolute` error. Corresponding plugin is not tracked in this worktree. | Correct the persisted plugin path after locating its configuration; do not misattribute this to NVIDIA. |

### Stale socket impact and local lifecycle correction

Homepage had **10,589 consecutive failed healthchecks**. A read-only request to
the bound Docker socket returned `ECONNREFUSED`, while its web page returned
HTTP 200: the UI is serving, but Docker integration is not.

Alloy logged **400 Docker-connection errors in roughly 20 seconds**. cAdvisor
exported **1,337 of 2,415 timestamped samples about 45.7 days old**; Prometheus
rejected exactly **1,337 samples per scrape** even though all three inspected
targets reported `up`. The VPN watcher retried its disconnected event stream
every five seconds. Current VPN namespace attachments were correct, but
automatic recovery was unavailable.

The proposed `docker-socket-consumers.service` runs after Docker starts and
follows daemon restarts. Its helper serially recreates only known, currently
running socket-consuming services in project `compose`: Homepage, Alloy,
cAdvisor and the VPN namespace watcher. It uses the main Compose entry point,
does not pull/build images or start dependencies, and leaves absent/stopped
consumers alone. It shares an exclusive lock with the daily updater.

This retains live-restore for unrelated workloads. It deliberately causes a
brief interruption to selected consumers and applies their checked-out Compose
configuration, so it is a maintenance action, not a diagnostic. Uncoordinated
manual Compose commands are outside the shared lock. No broad `/run` mount,
weakened healthcheck, or suppression of stale Prometheus timestamps was added.
Changing the OS update policy alone would not fix these existing stale mounts.

### Recyclarr secret template

The tracked template previously used `http://localhost:8989` and
`http://localhost:7878`, which address Recyclarr's own container rather than
Sonarr/Radarr. It now uses `http://sonarr:8989` and `http://radarr:7878` on the
existing shared `starr` network.

The actual production config is mounted from `${DATA}/recyclarr/config`.
Its private `secrets.yml` must define `sonarr_url`, `sonarr_apikey`, `radarr_url`,
and `radarr_apikey`. The observed missing key is specifically `sonarr_url`;
the audit did not inspect secret contents or establish that the other keys are
missing. Editing the example does **not** repair the deployed secret file.

## Healthy evidence and lower-priority observations

| Area | Observation | Interpretation |
|---|---|---|
| RAID | RAID6 `md0`: 11/11 active members, one spare, all `U`, degraded count 0, idle and clean, mismatch count 0. | No current degraded-array evidence. |
| Filesystems | Root: 35% used, about 1.1 TiB available. `/data`: 78% used, about 15 TiB available. `/boot`: 25%. Root/data inode use 16%/1%. | No immediate capacity or inode emergency. `/data` merits growth planning, not blind deletion. |
| Memory | 125 GiB RAM, about 112 GiB available; 55 GiB swap occupied. Short `vmstat` sample shows no swap-out and only small swap-in activity, CPUs roughly 96% idle. | Occupied swap alone is not evidence of current memory pressure. Do not clear swap or drop caches just to reduce these numbers. |
| Kernel faults | No matching OOM, filesystem corruption, I/O error, NVIDIA Xid, or hardware-error lines in the reviewed seven-day kernel journal. | No observed recent evidence of these faults; not a hardware certification. |
| SMART monitoring | `smartd` active; many recent self-tests explicitly completed without error. Sample HDD temperature 30 C; NVMe0 38-44 C during inspection. | Normalized SMART attribute values such as `Temperature_Celsius 123` are not temperatures in Celsius. Raw drive reports still need privileged review. |
| Backups | Latest database/Vaultwarden job, daily offsite job, and weekly offsite job exited 0. Daily rclone logs contain retry failures followed by success. | Latest jobs succeeded; no restore test or remote backup integrity check was performed. |
| Networking | Both ixgbe bond members up at reported 10 Gb/s, zero link-failure counters; expected stable IPv4/IPv6 addresses and default routes present. | No observed link failure. Preferred-member configuration still needs the correction above. |
| GPU USB-C controller | Boot-time `ucsi_ccg` I2C timeout/probe error on August 1. | Separate from the current NVML mismatch. No demonstrated workload impact; no blanket module blacklist proposed. |
| Other boot warnings | Out-of-tree NVIDIA module taint, disabled LVM-cache discard passdown, old `tun0` GRO warning. | Not enough evidence for driver replacement, filesystem tuning, or module removal. |
| Journal coverage | Kernel reports a `/dev/kmsg` buffer overrun on September 13. | Some kernel messages were lost; absence of journal errors is not proof none occurred. |
| Containers | 93/93 running; 45 healthy, Homepage unhealthy, 47 without healthchecks; no inspected OOM/state errors. Three containers have one historical restart each and weeks of current uptime. | Running is not equivalent to functional, particularly for the monitoring failures above. |
| Docker daemon | Docker 29.8.0, overlay2, cgroup v2; no daemon-reported warnings and zero actual daemon warning records in 24 hours after excluding container log records. | Container logs routed through journald must not be counted as daemon faults. |
| Docker cleanup | About 11.17 GB build cache, 763 MB images, and 5.051 GB volumes reported reclaimable; 525 volumes, 24 active. | No capacity emergency. Unused volumes can contain valuable data; review ownership before deleting anything. |
| qBittorrent memory | Cgroup accounting approximately 116.6 GB file cache versus 53 MB anonymous memory, no OOM events. | The large total is not evidence of a heap leak. |
| GPU consumers | Six inspected consumers have NVIDIA CDI requests; bounded logs did not show CUDA/NVML failures. | Correct device requests and quiet logs do not establish working acceleration; the confirmed host mismatch remains unresolved. |

## Local changes

All proposed host corrections are in `nixos/configuration.nix`; operating
policy and caveats are documented in `nixos/README.md`. Socket recovery uses
`docker/scripts/reconcile-docker-socket-consumers.sh`, with details in
`docker/docs/DOCKER-SOCKET-RECOVERY.md`. Recyclarr setup corrections are in its
example secret template and README; no private secrets were created.

- Stage NixOS auto-upgrades with `operation = "boot"`; keep automatic reboot off.
- Correct the preferred networkd bond member without changing IPs, MAC, or ports.
- Run each vdirsyncer pair independently, attempt all pairs, and preserve errors.
- Keep Git maintenance in the foreground during the daily container update.
- Preserve an active scrub monitor across configuration switches.
- Connect Docker update and scrub failures to the existing ntfy handler.
- Reconcile running socket consumers after Docker starts/restarts, serialized
  with the daily updater; leave unrelated and intentionally stopped services alone.
- Correct Recyclarr's non-secret example service URLs.

`nixos/tests/test_health_cleanup.py` evaluates the configuration and exercises
service scripts with mocked commands. It covers all eight combinations of sync
pair success/failure, update success plus Git/ownership/image-pull failures,
the staged upgrade command, primary bond setting, scrub restart policy, and
failure-notification wiring.

The Docker helper has separate mocked regression coverage for service selection
and command failures in `docker/tests/test_reconcile_docker_socket_consumers.py`.
All four host test methods and seven Docker-helper test methods passed,
including the success/failure combinations above. Neither test suite runs real
production mutations.

## Validation and limitations

The local NixOS evaluation passed all module assertions, both with the local
Nixpkgs source and with production's exact channel revision:
`e554fab72f81915600f3f449b786fd9af40439a5`.
The regression checks passed against both sources. Nix syntax and patch
whitespace checks passed, as did the repository's YAML lint for the modified
Recyclarr example. The complete Linux system derivation also evaluated
successfully against production's pinned revision. This is evaluation and
mocked execution, **not a Linux system build or live deployment**.

Option definitions were verified in the installed channel and upstream source:

| Option | Type / default | Meaning used here |
|---|---|---|
| `system.autoUpgrade.operation` | Enum `"switch"` or `"boot"`; default `"switch"` | Select rebuild action; `"boot"` is an upstream example. |
| `system.autoUpgrade.allowReboot` | Boolean; default `false` | Controls automatic reboot, not whether a live switch occurs. |
| `systemd.network.networks.<name>.networkConfig` | Attribute set of systemd unit values; default `{}` | `PrimarySlave` is a recognized boolean network setting. |
| `systemd.services.<name>.restartIfChanged` | Boolean; default `true` | Whether an active service restarts when its definition changes during a switch. |
| `systemd.services.<name>.wantedBy`, `.after`, `.requires`, `.partOf` | Lists of unit names; default `[]` | Start reconciliation with Docker, order it after readiness, and propagate daemon stop/restart. |
| `systemd.services.<name>.serviceConfig` | Attribute set of systemd service values; default `{}` | A oneshot with `RemainAfterExit=true` remains attached to the daemon lifecycle. |

References:

- [NixOS auto-upgrade module](https://github.com/NixOS/nixpkgs/blob/e554fab72f81915600f3f449b786fd9af40439a5/nixos/modules/tasks/auto-upgrade.nix)
- [NixOS networkd bond translation](https://github.com/NixOS/nixpkgs/blob/e554fab72f81915600f3f449b786fd9af40439a5/nixos/modules/tasks/network-interfaces-systemd.nix)
- [Git automatic maintenance configuration](https://git-scm.com/docs/git-config#Documentation/git-config.txt-maintenanceautoDetach)

Passwordless sudo was unavailable. No privilege workaround was attempted.
Raw SMART/NVMe device reports, complete LVM/cache metadata, privileged firewall
state, and BMC hardware sensors were not verified. No intrusive disk self-test,
filesystem check, stress test, network failover, application write, or restore
exercise was run.

## Deferred maintenance

Before any deployment, review the behavior changes, arrange console access for
the bond change, and schedule a reboot to load matching kernel/NVIDIA components.
Do not treat a live switch alone as a driver repair. After an approved rollout,
verify `nvidia-smi`, affected container acceleration, the selected bond primary,
the next automatic update, a complete scrub-monitor run, and fresh Docker socket
connectivity/metrics for all four consumers. Confirm stopped services remain stopped.

Google authorization needs a separate interactive repair followed by controlled
per-pair synchronization. Preserve existing local data and synchronization
state. Hardware-level drive diagnostics and backup restore verification remain
separate maintenance tasks.

Recyclarr needs its missing production secret configuration repaired; qbit-manage
and Tdarr need persisted application settings reviewed. Recheck AdGuard's upstream
errors before changing DNS providers. No blind Docker volume pruning is recommended.

No server pull/rebuild/reboot instructions have been executed or requested as
part of this audit; this branch remains local for review.
