# qbit-manage inactivity-only cleanup policy

## Unattended operation and qBittorrent compatibility

qbit-manage runs unattended in dry-run mode. It was paused from early October
2026 while its stable release did not support qBittorrent 5.2.4. On October 24,
2026 the owner chose to keep qBittorrent on `:latest` for security updates and
have qbit-manage follow it by installing the newest `qbittorrent-api` on each
nightly build (see [Pinned implementation](#pinned-implementation)), so the
opt-in Compose profile was removed and `qbit-manage` was restored to
`vpn-netns-watcher`'s `SIBLING_SERVICES`.
Do not bypass the version check or enable deletion just to clear startup errors.

## What the current policy previews

Every 30 minutes, the manager previews category/tag updates, unregistered-torrent
removal, no-hardlink tagging for the media categories (`movies`, `tv`,
`anime-movies`, `anime-tv`, `indian-movies`, `indian-tv`, and `music`), and share-limit
cleanup. **Dry-run remains enabled; these torrent actions are not applied.**

The `noHL` cleanup group requires at least 14 days seeded, seven days inactive,
and two reported seeders, with no ratio requirement. Other torrents default to
no cleanup. Missing hardlinks are a storage signal, not proof that an item has
been watched or imported successfully. Reported seeder counts are not a guarantee
that a torrent can be downloaded again.

Unregistered-torrent removal is a separate path and does not inherit those three
gates. The current settings permit incomplete torrents, use a ten-minute grace
setting, and cap removals at ten per tracker per run. The recycle bin retains
removed data and saved `.torrent` metadata for 14 days; after that they can be
permanently deleted. Some share-limit actions also resume paused torrents.

Before a first real-mode run, review actual dry-run candidates and separately
decide whether to enable unregistered removal. Prefer leaving that removal path
off initially rather than treating `QBT_DRY_RUN=false` as only the conservative
inactivity cleanup toggle.

## Pinned implementation

`compose.downloads.yml` builds `qbit-manage-inactivity:4.14.0-3` from the exact
upstream image below. It was bumped from 4.13.0 on October 24, 2026 because
4.13.0's bundled `qbittorrent-api` refused to run against qBittorrent 5.2.4.

qBittorrent stays on `:latest` for security updates. qbit_manage's only
compatibility gate is its bundled `qbittorrent-api`, so the Dockerfile installs
the newest `qbittorrent-api` from PyPI on every build (an `ADD` of the PyPI
metadata invalidates that layer when a release is published). The nightly
`docker compose build --pull` therefore follows qBittorrent automatically,
normally a few days after each qBittorrent release. During that lag qbit-manage
logs "only compatible with ... or lower" and skips its runs (it is dry-run
only). If the newest library breaks the build, the previous image keeps running.
Bumping the qbit_manage pin itself (and the patch source hashes) stays manual.
Current pin:

- Image manifest: `sha256:0153204c727b8cd219c87cd22d5e5833e392436923577455e3c84ceb73835c7d`
- Upstream version: `4.14.0`
- Source revision: `e6b2ba0b735b96cb153ef874d176ca6d0fffbf49`
- `qbittorrent-api`: newest PyPI release at build time (upstream 4.14.0 bundles
  2026.10.0, which stops at qBittorrent 5.2.4)

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

## Category and no-hardlink mapping

`cat:` must list **every** qBittorrent category with its real save path
(qbit-manage assigns categories from save paths, and `cat_update_all: true`
re-checks every torrent). `nohardlinks:` keys must be real category names too.
The Starr apps use media-type categories, not app names, so the mapping is:

```yaml
cat:
  movies: /data/torrents/movies
  tv: /data/torrents/tv
  anime-movies: /data/torrents/anime/movies
  anime-tv: /data/torrents/anime/tv
  indian-movies: /data/torrents/indian/movies
  indian-tv: /data/torrents/indian/tv
  music: /data/torrents/music
  books: /data/torrents/ebooks
  roms: /data/torrents/roms
  prowlarr: /data/torrents/prowlarr
  zim: /data/openclaw-zim
nohardlinks:
- movies
- tv
- anime-movies
- anime-tv
- indian-movies
- indian-tv
- music
```

Each category's qBittorrent save path must be distinct, so `prowlarr` saves to
`prowlarr` rather than the `/data/torrents` root. Books, ROMs, Prowlarr manual
grabs, and ZIMs are never hardlinked into a library, so they stay out of
`nohardlinks` (they would always be tagged `noHL` and cleaned up). When adding
a category in qBittorrent, add it here as well.

Upstream validates share limits before directories: the old validator error
masked the missing backup path. It also adds default fields/directories even
during dry-run; dry-run protects torrent actions, not every configuration write.
Stop qbit-manage before editing its config, keep a private mode-600 backup,
fill only the blank `torrents_dir`, and recreate only that service using the main
Compose entry point. Never commit the private configuration.

Afterward verify a complete run without `ERROR`, `CRITICAL`, `Config Error` or
tracebacks. The application can print `Finished Run` and exit successfully even
when it caught a configuration failure. Avoid overlapping verification with the
scheduled run. For a genuine one-shot, override the inherited scheduling
environment for that exec only:

```bash
docker compose exec -T -e QBT_RUN=true -e QBT_DRY_RUN=true \
  qbit-manage python3 /app/qbit_manage.py --run --dry-run
```

`QBT_RUN=false` in the normal container environment overrides the CLI `--run`
flag; omitting the exec-time override starts another scheduler instead of exiting.
The command above leaves the service's normal schedule and dry-run setting intact.

## Local validation

With Docker available, build without starting any service:

```bash
docker build -t qbit-manage-inactivity:4.14.0-3 docker/dockerfiles/qbit-manage
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
- [Upstream validator](https://github.com/StuffAnThings/qbit_manage/blob/e6b2ba0b735b96cb153ef874d176ca6d0fffbf49/modules/config.py#L1051-L1071)
- [Runtime cleanup gates](https://github.com/StuffAnThings/qbit_manage/blob/e6b2ba0b735b96cb153ef874d176ca6d0fffbf49/modules/core/share_limits.py#L743-L843)
- [Upstream inactivity minimum-seeding-time fix](https://github.com/StuffAnThings/qbit_manage/pull/1319)
