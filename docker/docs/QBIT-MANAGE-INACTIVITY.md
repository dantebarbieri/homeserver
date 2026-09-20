# qbit-manage inactivity-only cleanup policy

`compose.downloads.yml` builds `qbit-manage-inactivity:4.13.0-1` from the exact
upstream image deployed on September 20, 2026:

- Image manifest: `sha256:ea04167f627e506b3691304f4c639a52c05584cc9aea4af7ec87d4ed1299e7f5`
- Upstream version: `4.13.0`
- Source revision: `906af0f74818abaaa62f9f22e1e4e73ccb0d2bd5`

The existing policy deliberately has no ratio cap and no maximum seeding time.
Cleanup eligibility requires all of: at least 14 days seeded, at least seven days
inactive, and at least two seeders. The private configuration remains in
`${DATA}/qbit-manage/config/config.yml`; it is not copied into this image or repo.

## Narrow patch and safety

Upstream rejects positive `min_seeding_time` without a positive `max_ratio`, even
though its runtime inactivity-cleanup branch already checks the minimum seeding
time. The patch changes only that validator, permitting the exception only when:

```text
max_ratio == -1 AND max_seeding_time == -1 AND max_last_active > 0
```

No runtime cleanup, duration conversion, seed-count, tagging or deletion code is
changed. Other validation errors remain errors. In particular, zero/global ratios,
finite/global maximum seeding times and missing/nonpositive inactivity limits do
not qualify for the exception. Existing upstream inactivity rounding to minutes
is unchanged.

**Dry-run remains true** in Compose and is also the derived image's default.
Do not add a `commands.dry_run: false` override to the private configuration:
upstream configuration commands can override environment settings. Do not disable
dry-run to test this repair. Eligibility is only a preview while dry-run is active.

The build checks full SHA-256 hashes of upstream configuration, conversion and
runtime source before applying the single replacement. Any unexpected source or
already-applied patch fails the build. It then runs tests against those actual
image sources, without accessing `/config`, qBittorrent, credentials or media.
The base entrypoint and command are inherited unchanged.

## Torrent backup path

With `recyclebin.save_torrents: true`, `directory.torrents_dir` means
qBittorrent's **`.torrent` metadata backup directory**, not downloaded media.
Compose mounts the existing
`${DATA}/qbittorrent/config/qBittorrent/BT_backup` read-only at
`/qbittorrent/BT_backup`. Missing host directories fail deployment rather than
silently creating an empty backup location.

The private configuration must contain:

```yaml
directory:
  root_dir: /data/torrents/
  recycle_bin: /data/torrents/.RecycleBin
  torrents_dir: /qbittorrent/BT_backup
```

Preserve the rest of that mapping and configuration. No `remote_dir` translation
is needed because both applications already use `/data/torrents`. Keep torrent
backup saving enabled and the existing 14-day recycle retention.

Upstream validates share limits before directories: the old validator error
masked the missing backup path. It also adds default fields/directories even
during dry-run; dry-run protects torrent actions, not every configuration write.
Stop qbit-manage before editing its config, keep a private mode-600 backup,
fill only the blank `torrents_dir`, and recreate only that service using the main
Compose entry point. Never commit the private configuration.

Afterward verify a complete run without `ERROR`, `CRITICAL`, `Config Error` or
tracebacks. The application can print `Finished Run` and exit successfully even
when it caught a configuration failure. A one-shot verification can use
`docker compose exec -T qbit-manage python3 /app/qbit_manage.py --run --dry-run`;
avoid overlapping it with the scheduled run, and keep dry-run enabled.

## Local validation

With Docker available, build without starting any service:

```bash
docker build -t qbit-manage-inactivity:4.13.0-1 docker/dockerfiles/qbit-manage
docker compose --env-file docker/sample.env -f docker/compose.downloads.yml config --quiet
```

For source-level tests without a Docker daemon:

```bash
python3 -m venv docker/dockerfiles/qbit-manage/.venv
docker/dockerfiles/qbit-manage/.venv/bin/python -m pip install -r docker/dockerfiles/qbit-manage/requirements-test.txt
PYTHONDONTWRITEBYTECODE=1 docker/dockerfiles/qbit-manage/.venv/bin/python -m unittest discover -s docker/dockerfiles/qbit-manage/tests -v
```

Source-level tests download the three hash-verified files from the immutable
upstream revision into memory. Alternatively, set `QBIT_MANAGE_SOURCE_ROOT` to an
existing source checkout. Build-time tests use `/app` and require its source to
already be patched; they do not download source.

Tests invoke actual upstream configuration conversion, validation, cleanup
eligibility, eligible-item queuing and cleanup functions. Application startup/API
clients, logging, filesystem existence checks and torrent mutation methods are
isolated. They reproduce the original
failure, verify all three gates and dry-run nonmutation, preserve other invalid
configuration rejection, and detect patch/source drift.

## Maintenance, deployment and rollback

Build and review this image before any separately authorized deployment. Use the
main Compose project from `/srv/homeserver/docker`; never deploy the category file
as a separate project. Buildable local images must be excluded from registry pulls
(the host updater uses `docker compose pull --ignore-buildable`).

This patch does not auto-follow `latest`. On upgrade, deliberately update the base
digest, source revision/hashes and derived image tag together; inspect upstream
validation and all runtime gates, then rebuild and rerun the matrix. Remove the
patch when upstream supports the exact inactivity-only policy. Do not bypass a
hash failure by weakening the check.

Rollback means reverting the Compose image/build selection to the pinned upstream
base, keeping dry-run enabled. That restores the known validation failure rather
than silently changing seeding/deletion policy. Reverting the validator patch
does not require undoing the correct torrent-backup path or read-only mount.

Sources:
- [Upstream validator](https://github.com/StuffAnThings/qbit_manage/blob/906af0f74818abaaa62f9f22e1e4e73ccb0d2bd5/modules/config.py#L1038-L1058)
- [Runtime cleanup gates](https://github.com/StuffAnThings/qbit_manage/blob/906af0f74818abaaa62f9f22e1e4e73ccb0d2bd5/modules/core/share_limits.py#L733-L833)
- [Upstream inactivity minimum-seeding-time fix](https://github.com/StuffAnThings/qbit_manage/pull/1319)
