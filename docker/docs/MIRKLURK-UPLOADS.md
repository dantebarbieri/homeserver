# MirkLurk native uploads: storage and recovery

This supplements [MIRKLURK.md](MIRKLURK.md). The user approved a brief daily
wiki interruption for consistent backups. **This runbook does not itself
authorize a live deployment, reboot, restore drill or account grant.**
The app image/source pin stays unchanged until the coordinated upload revision
is reviewed and its deployment gates pass.
Infrastructure regressions run in GitHub-hosted CI; native upload integration
belongs to the companion app's CI. General-purpose disposable app smoke tests
must not run on the homeserver. A scoped isolated restore drill requires separate
authorization; approving it does not authorize unrelated test containers.

## Verified storage and proxy contract

Scoped read-only production inspection on 2026-10-02 confirmed:

| Resource | Observation / unchanged contract |
|----------|----------------------------------|
| Images | `/srv/docker/data/mirklurk/images` already mounted RW at `/var/www/html/images`; UID 1000/GID 131, mode 2770 with access/default UID 33 ACL and default UID 1000 ACL |
| Apache access | Effective UID/GID 33 read/write/traverse check succeeded; ownership need not become `33:33` |
| Private history | Keep `/var/www/html/images/deleted`; absent at inspection, must not relocate history later |
| Branding | Dedicated RO mount, UID 1000/GID 131 mode 2750 and UID 33 read/traverse ACL; preserve bytes and mount |
| Backups | `/srv/docker/data/mirklurk/backups`, UID 1000/GID 131 mode 2700 |
| Capacity | Root filesystem about 1019 GiB free, 18% inodes used; recheck at rollout |
| NPM | `mirklurk.wiki` proxy host 71 has no body-limit override; inherited `client_max_body_size 2000m` exceeds PHP's 12 MiB request limit |

No images migration, chown, NPM, DNS, TLS, router or firewall changes are needed.
Never mount an empty directory over the deployed images tree, replace existing
ACLs with initial-install examples, or recursively chown shared directories.
Keep existing imports, originals, previous versions, deleted files and branding.
`create_host_path: false` makes a missing bind source an error, not empty storage.

The **only new app mount** is
`${DATA}/mirklurk/backup-control` -> `/var/lib/mirklurk-backup`, read-only.
Provision just this dedicated directory as the existing host data owner, mode
0700 with Apache UID 33 read/traverse ACL (`setfacl -m u:33:rx,m::rx`).
The privileged host snapshot helper creates its `read-only` file exclusively,
mode 0644; the app uses native `$wgReadOnlyFile` at that exact path.
Keep Compose's literal `MW_READ_ONLY: ""`. No sidecar mount or privilege changes.

The reviewed app must supply PNG/JPEG/WebP-only uploads, 10 MiB per file,
12 MiB PHP POST capacity, autoconfirmed after 24 hours and five edits, manual
`confirmed`, 20 uploads/hour per ordinary uploader, own-file replacement only
(admins any), hard 12,000,000 pixels and 8192 pixels per axis, and no URL upload.
It must deny HTTP access to `images/deleted` and `images/temp`, disable script
handlers/execution and listing throughout uploads, and disable `.htaccess`
overrides using Apache configuration outside writable storage.

Preserve the current proxy route, client-IP trust and canonical
`https://mirklurk.wiki` origin. If the effective proxy limit changes before
rollout, the owner must ensure it is at least `12m`; do not change a global
limit for unrelated sites. Require an actual near-10-MiB multipart upload
end-to-end in acceptance, not just a configuration check.

## Consistent snapshots

**An online SQL dump and an independently copied live images tree are not a
consistent recovery point.** The unprivileged six-hour SQL sidecar remains
unchanged for supplemental database recovery/diagnostics. Recover uploaded
files from a complete bundle, not newer SQL plus arbitrary offsite files.

`mirklurk-release.py snapshot` runs as root under the existing
`/run/lock/homeserver-compose.lock`. It checks actual mounts, health and capacity,
exclusively creates the native maintenance marker, then gracefully stops only
the **existing frontend container**, using Apache's `SIGWINCH`. Forced/nonzero/
OOM stops fail instead of claiming consistency. The read-only marker alone
is not a writer-drain barrier.

With the frontend stopped, the helper requests a fresh checked SQL dump from
the scoped sidecar and archives it with all of `images/` and `branding/`.
It streams the reviewed backup script to the existing client and requests a
unique snapshot SQL file; it never reads the replaceable daily SQL filename,
which an overlapping six-hour online dump could overwrite. Streaming also
avoids a stale file-bind inode after a Git update, without recreating the
sidecar. The unique intermediate SQL is removed after capture and excluded
from offsite sync.
Each bundle contains:

| Member | Coverage |
|--------|----------|
| `database.sql.gz` | Fresh InnoDB transaction dump with schema/gzip checks |
| `manifest.json` | UTC timestamp, runtime image, source revision and quiescence method |
| `images/` | Existing imports, current originals, `archive/` prior versions, private `deleted/`, `thumb/`, temporary upload/stash data |
| `branding/` | All original/versioned approved branding, unmodified |

GNU tar preserves numeric ownership, POSIX ACLs and xattrs. Secrets remain
in the existing encrypted offsite coverage rather than the bundle. Sitemap
data is derived and can be regenerated.

The same frontend is restarted in a `finally` path without pulling/building/
recreating it. Integrity validation runs after readiness, then an immutable
timestamped mode-0600 bundle is atomically published under
`backups/snapshots/daily/`. Snapshot directories/files belong to the backup
directory's data owner. Daily bundles last seven days; Sunday bundles also
have a 28-day weekly hard link. Only complete publication updates
`.last-snapshot`. Prior bundles survive failures; retention never selects
SQL dumps or unrelated files.

Only the helper's own marker inode may be removed. Failed frontend recovery
leaves it in place and reports failure. SIGKILL, power loss or daemon failure
can leave the frontend stopped/read-only and require attended recovery.
Do not blindly clear a marker that may belong to another operator.

**Daily 03:15 backups interrupt public reads during dump/archive, and editing
until integrity validation completes.** Duration grows with data. Stop, dump,
archive and validation commands are bounded; archive creation has a ten-minute
limit. Failure attempts to recover the same frontend and alerts through the
existing NixOS `ntfy-failure@` handler. This is not zero downtime.

All CLI imports, jobs, direct DB maintenance, file moves and manual snapshots
must take the same Compose lock. Sitemap/updater helpers already do. Competing
application mounts are rejected. The known `code-server` administrative parent
mount of `/srv/docker/data` is reported, not stopped: **host/code-server
operators must not modify wiki files or run direct DB writers during backups.**
No guarantee is made for an administrator bypassing this coordination contract.

The hourly :45 `mirklurk-backup-check` timer fails on a missing/stale complete
snapshot (26 hours), remaining maintenance marker, unhealthy/stale SQL backup,
less than 5 GiB free disk, or less than 5%/10,000 free inodes, and uses ntfy.
Before stopping the app, snapshots additionally require room for the apparent
size of images, branding and retained daily SQL plus 5 GiB reserve. This is
monitoring/admission control, not an upload quota.

The existing 03:30 encrypted offsite sync includes published bundles without
new credentials/destinations. Incomplete staging directories and ephemeral
backup-control contents are excluded. Unique immutable bundle names prevent
SQL/files from different runs being mixed. A sync begun before publication
may miss that run until the next day. Verify the actual remote artifact, not
just an exit-zero rclone job; independently synced live images are supplemental.

## Restore drill and disaster recovery

Before live acceptance, require a full snapshot and a successful restore into
a **new disposable DB and separate file directories** with matching pinned
MariaDB/app images. Keep the restored app unpublished; never attach production
images, branding or DB volumes to a drill. Retrieve the exact bundle through
the existing encrypted offsite mechanism and verify its checksum against the
local immutable bundle. Check gzip/tar integrity and review `manifest.json`
and archive member paths before extracting as root into a new private directory:

```bash
tar --extract --gzip --acls --xattrs --numeric-owner \
  --file "$bundle" --directory "$recovery_directory"
gzip -t "$recovery_directory/database.sql.gz"
```

Use the pinned MariaDB client to import `database.sql.gz` into the disposable
DB with scoped test credentials supplied via a private file, not arguments.
Recover associated runtime secrets only through the authorized encrypted path.
Compare page/revision/user counts, known page text, `image`/`oldimage`/
`filearchive` records, original/prior/deleted-file hashes and approved branding.
Verify UID/GID 33 can traverse/read/write the restored tree, thumbnails
regenerate, and `/images/deleted` and `/images/temp` are denied over HTTP.
Do not publish private files to prove they exist. Exercise upload, replacement,
deletion and undelete against disposable data, then remove only the explicitly
named disposable resources.

For real recovery, keep writers offline, restore **SQL and both trees from
the same bundle**, preserve numeric ownership/ACLs, supply matching secrets
and runtime, and validate before publishing. Never extract over a live tree.
Provision an empty backup-control directory; never restore an old maintenance
marker. Independent newer SQL needs a separately proven file/history match.
The initial administrator password file may no longer contain the current
password. Unit tests/archive integrity alone do not prove restoreability.

## Installing scheduling with an operator-planned reboot

Use the normal, reviewed `/etc/nixos/configuration.nix` configuration, which
resolves to `/srv/homeserver/nixos/configuration.nix` and imports the tracked
hardware configuration. Do not substitute an old pinned generation for an
operator's planned `nixos-rebuild boot --upgrade`.

The root-owned `/var/lib/mirklurk-upload-deployment/hold` file is a **deployment
hold**, not MediaWiki's native read-only marker. While it exists, declarative
`ConditionPathExists` guards prevent both the services and timers for
`docker-compose-update`, `nixos-upgrade`, `rclone-offsite-daily`,
`mirklurk-snapshot`, and `mirklurk-backup-check` from starting. It survives
reboot, blocks persistent-timer catch-up, and prevents the scheduled OS upgrade
from replacing the attended boot selection. It does not stop existing jobs,
block arbitrary root/CLI commands, or pause the six-hour SQL sidecar.

Only after the guard changes are merged and the coordinator has confirmed the
exact clean canonical revision and no competing host writers, run this root
preparation. It pauses timers but never kills services or changes containers.
If it fails, leave timers paused and investigate before building or rebooting.

```bash
sudo bash -eu <<'SH'
exec 9</run/lock/homeserver-compose.lock
flock -x -w 30 9
state=/var/lib/mirklurk-upload-deployment
test ! -e "$state"
test ! -L "$state"
systemctl stop docker-compose-update.timer nixos-upgrade.timer rclone-offsite-daily.timer
for name in docker-compose-update nixos-upgrade rclone-offsite-daily; do
  test "$(systemctl show "$name.service" -p LoadState --value)" = loaded
  test "$(systemctl show "$name.service" -p ActiveState --value)" = inactive
done
mkdir -m 0700 "$state"
umask 077
printf '%s\n' 'Awaiting coordinated post-reboot wiki acceptance.' > "$state/hold"
readlink -f /run/current-system > "$state/previous-active"
readlink -f /nix/var/nix/profiles/system > "$state/previous-boot"
git -c safe.directory=/srv/homeserver -C /srv/homeserver rev-parse HEAD > "$state/source-revision"
SH

sudo nixos-rebuild boot --upgrade
sudo bootctl list --no-pager
```

`boot --upgrade` can update packages/kernel and the next-boot entry; it does
**not** activate those changes or restart the wiki now. Do not use `switch`.
Keep the hold if the build/bootloader installation fails. Before reboot, verify
build success, the intended default boot entry, the unchanged running generation,
and all ten service/timer guards in the selected generation. A successful build
without a correctly installed boot entry is insufficient. Retain the recorded
previous generations and existing known-good wiki image; do not garbage-collect
them during this window.

After that review, the operator may run `sudo reboot` over SSH. The disconnect
is expected; this reboots the whole host, not just the wiki. Have local or
independent BMC console access first: the host-proxied `ipmi.danteb.com` cannot
be the only fallback while the host is down. If boot fails, use the retained
generation from the boot menu. **An older generation lacks these guards**:
keep the updater paused and re-establish coordination before any further action.
Restoring a previous next-boot selection is a separate reviewed `boot` action,
never a blind live switch to newer or older packages.

After reconnecting, verify the booted/running generation, SSH/networking,
Docker and storage, the original wiki/DB/SQL-backup health and image identities,
and all five guarded timers/services loaded but inactive with the hold present.
Inspect failed units before proceeding. Do not remove the hold just because
reboot succeeded. Baseline capture, offsite roundtrip, isolated restore and
app-only rollout remain separate authorized steps below. Refresh any staged
helper's exact canonical-SHA guard after reviewed source changes; never bypass it.

Only after joint acceptance, verify that this is still the deployment's own
hold, remove that **one file**, and start the snapshot/check/offsite timers,
then the OS-upgrade and Docker-updater timers. Inspect actual next triggers
and results; persistent timers may run immediately when resumed. Never delete
another operator's hold, clear the entire directory, or resume the updater
while another coordinated deployment is unfinished.

## Attended deployment sequence

1. Coordinate reviewed app and infrastructure revisions, exact local image
   build and permissions, with explicit authorization for live activation.
   Pause the updater before merge using the existing maintenance
   procedure. Confirm no manual writers, inventory/hash existing images and
   branding without exposing contents, and recheck actual mounts.
2. Provision only the dedicated backup-control path as above before merging
   its mount. Preserve every other bind path and directory. The snapshot and
   release preflight deliberately reject an app missing this control mount.
3. Under the shared lock, an authorized bootstrap may recreate just the
   **existing pinned app** with the control mount, then take a baseline with
   `snapshot` and prove its isolated restore. Alternatively take an attended
   offline SQL/files baseline first. Do not bypass the helper's mount guard.
   The old pinned image does **not** honor the new `$wgReadOnlyFile` path;
   its baseline is consistent because SQL and files are captured while the
   frontend is stopped, not because the marker exists. Native maintenance
   protection takes effect only with the coordinated app release.
4. Pin the coordinated, reviewed upload build/source in a subsequent reviewed
   homeserver revision and activate only `mirklurk` using the guarded runtime
   procedure. `deploy` now requires a recent complete snapshot as well as its
   fresh SQL dump. Keep DB/backup/proxy containers and all current mounts intact.
5. Verify upload denial/acceptance, boundaries, rate limits, private-path
   denial, original file/branding hashes and the isolated recovery lifecycle.
   Take a fresh complete snapshot and verify public recovery. Only then may
   the authorized wiki admin verify exact `DavidLokison` in `Special:ListUsers`
   and grant **confirmed only** through `Special:UserRights`, never administrator.
   No production username or account rights were changed by this preparation.
6. Install the daily snapshot and hourly health timers through the separately
   reviewed NixOS activation or planned-reboot procedure above, keeping the
   deployment hold until acceptance; a full switch may include other pending OS changes.
   Verify timers, ntfy failures and actual offsite recovery. Until installed,
   an authorized operator must run/check snapshots at least daily. A committed
   timer is not a running schedule. Resume the updater after joint acceptance.

Once the reviewed helper is installed, these commands use canonical config
and must not run inside another holder of the Compose lock:

```bash
z /srv/homeserver
sudo nix shell nixpkgs#python3 --command python3 docker/scripts/mirklurk-release.py snapshot
nix shell nixpkgs#python3 --command python3 docker/scripts/mirklurk-release.py check-backups
systemctl list-timers mirklurk-snapshot.timer mirklurk-backup-check.timer --no-pager
journalctl -u mirklurk-snapshot.service -u mirklurk-backup-check.service -n 40 --no-pager
```

After an interrupted backup, first establish why the frontend stopped and
whether any helper/import still owns the lock. Recover the same pinned
frontend under that lock, verify health, then remove only a reviewed stale
`backup-control/read-only` marker not belonging to another maintenance task.
Never auto-clear all locks or restore production SQL as a restart fix.
