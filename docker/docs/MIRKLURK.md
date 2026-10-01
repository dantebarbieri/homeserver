# MirkLurk wiki

**Nginx Proxy Manager, DNS, and TLS are owner-managed prerequisites.** This
runbook does not discover credentials, request certificates, or create/change
proxy routes. The Docker services do not need NPM or provider credentials.

The application, nonsecret MediaWiki configuration, and curated source pages
live in [dantebarbieri/mirklurk-wiki](https://github.com/dantebarbieri/mirklurk-wiki).
This repository owns only the homeserver's Compose, storage, backup, and
Homepage integration. Do not duplicate `LocalSettings.php` or page content here.

**Deployment is a separate, explicitly approved step.** Preparing this
integration does not authorize DNS, certificate, reverse-proxy, or existing
credential discovery or changes. Those remain under the operator's control.

## Deployment contract

| Item | Value |
|------|-------|
| External clone | `/srv/docker/mirklurk-wiki`, reviewed build source only |
| Build | Operator builds `deploy/Dockerfile` once from the reviewed external release; no Compose build fallback |
| App | `mirklurk`, Apache port 80, exact local `sha256` image ID in `compose.websites.yml`, `pull_policy: never` |
| Public URL | `MIRKLURK_SERVER_URL`; current production is `https://mirklurk.wiki` (the initial-domain Compose fallback is not the live value) |
| Proxy trust | `MIRKLURK_TRUSTED_PROXY_CIDRS`, verified proxy addresses only |
| Database | `mirklurk-db:3306`, database/user `mirklurk`, named volume `compose_mirklurk-db` |
| Images | `${DATA}/mirklurk/images` -> `/var/www/html/images` |
| Branding | `${DATA}/mirklurk/branding` -> `/var/www/html/branding` (read-only) |
| Sitemap | `${DATA}/mirklurk/sitemap` -> `/var/lib/mirklurk-sitemap` (UID/GID 33, mode 0755 or inherited-setgid 2755) |
| Secrets | `${DATA}/mirklurk/secrets` -> individual `/run/secrets/` files |
| Local SQL dumps | `${DATA}/mirklurk/backups`, owned by `${UID}:${GID}` |

The app joins the existing `proxy` network and the dedicated `mirklurk`
network. The database and backup client join **only** `mirklurk`, which is
`internal: true`. None of the three services publishes a host port. No
additional firewall or router rule is part of this integration.

Always use the main `docker/docker-compose.yml` entrypoint with project name
`compose`. The external repository's standalone Compose is for development,
not a second homeserver stack.

## Before merging or starting

**Origin gate for installation and recovery:** the tracked Compose fallback,
`docker/sample.env`, and Homepage wiki `href`/`siteMonitor` still reference
the initial `https://wiki.mirklurk.danteb.com` hostname. They are not evidence
of the current canonical origin or of a verified supported alias. Do not
copy that sample value or rely on the fallback when recovering this instance.
Require the operator-approved `MIRKLURK_SERVER_URL=https://mirklurk.wiki`
and verify the resolved frontend's `MW_SERVER_URL` before exposing it;
an incorrect origin can issue cacheable redirects to the wrong host.
The existing production value is already correct and must remain unchanged
for this release. Aligning the legacy setup defaults and Homepage consumers
requires a separately reviewed follow-up, not this image-only rollout.

The daily homeserver updater pulls `main`, but it cannot pull or rebuild the
pinned wiki image. The authorized operator must build and verify that exact
image locally before its homeserver pin is merged. Keep the image available;
a missing image must fail rather than fall back to another release. Required
`.env` values, directories, and secret files must also already exist. Do not
deploy from an untracked production override or a feature-branch checkout:
the next updater can remove those containers with `--remove-orphans`.

Use a reviewed, committed wiki release and record its exact commit. The
external checkout belongs under `/srv/docker`, alongside the existing
external-app pattern; it is not part of `${DATA}` and is not the live database.
The homeserver updater does **not** pull this external repository.

For a first installation on another host, or a later application release,
build `deploy/Dockerfile` from that reviewed external checkout on the target
host, verify the resulting image, and record its full local `sha256` image ID.
Have a reviewed homeserver change pin that ID before starting the app. The
current local image ID is not a registry artifact that a fresh host can pull.

Create the wiki's own secret directory with mode `0700`. Individual secret
files must be readable by the mounted app (Apache UID 33), database, or backup
client, for example mode `0444` inside the protected directory. Do not apply
permissions to other services' directories or inspect/reuse their secrets.

| File | Used by |
|------|---------|
| `MIRKLURK_DB_PASSWORD` | App, database initialization, scoped backup client |
| `MIRKLURK_DB_ROOT_PASSWORD` | Database initialization only |
| `MIRKLURK_SECRET_KEY` | MediaWiki application |
| `MIRKLURK_UPGRADE_KEY` | MediaWiki maintenance |
| `MIRKLURK_CAPTCHA_QUESTIONS` | QuestyCaptcha: private JSON question -> answer arrays |
| `MIRKLURK_ADMIN_PASSWORD` | One-shot initial installer only; never the running app |

Generate independent random values for passwords and keys. The CAPTCHA file
contains original, harmless questions and answers, not game assets or copied
game text. Keep all values out of shell history, command-line arguments, logs,
Git, and chat. The initial administrator is `WikiAdmin`; store its generated
password only at
`/srv/docker/data/mirklurk/secrets/MIRKLURK_ADMIN_PASSWORD`.
An authorized operator retrieves it directly from that protected file.

Provision the images and backup directories as the host data owner before
starting. Grant Apache UID 33 access to the new images directory using an
owner-controlled POSIX ACL, without changing ownership of shared directories:

```bash
install -d -m 700 /srv/docker/data/mirklurk/images
setfacl -m u:33:rwx,m::rwx /srv/docker/data/mirklurk/images
setfacl -m d:u::rwx,d:u:33:rwx,d:g::---,d:m::rwx,d:o::--- /srv/docker/data/mirklurk/images
```

All data bind mounts use `create_host_path: false`. Persistent images remain
available for later explicitly approved CLI imports even while browser
uploads are disabled. Game assets stay outside Git.

`MIRKLURK_TRUSTED_PROXY_CIDRS` maps to the image's
`MW_TRUSTED_PROXY_CIDRS`. Use the reverse proxy's actual container-side
address(es), preferably `/32` and `/128`, not `0.0.0.0/0`, `::/0`, or the
entire shared web-service network. Verify forwarding and rate-limit behavior
with that configuration. Recheck the value if the proxy's address changes.

## Operator-supplied branding

Provision `${DATA}/mirklurk/branding` before merging this mount, even when
branding URLs are unset. It is separate from MediaWiki uploads and mounted
read-only in the frontend. The existing offsite backup includes it under
`/srv/docker/data/mirklurk/`; include it alongside images in pre-rollout and
recovery snapshots. This does not enable uploads or change wiki content.
Keep the host branding root operator-owned with mode `0700` plus an Apache
UID 33 read/traverse ACL (`setfacl -m u:33:rx,m::rx` on that directory).
Use `0755` for its versioned subdirectory and `0644` for the public files.

The operator supplied two Edym Pixels artworks and selected them for public
wiki branding. Display permission is operator-reported, confirmed 2026-09-25;
it is **not permission to redistribute the artwork in Git**. Preserve the
originals byte-for-byte and keep all artwork/derivatives out of Git, PRs,
issues, CI artifacts and runtime image builds. Store only the approved
originals, the required legacy derivative, and a public `attribution.txt`
under the versioned `branding/2026-09/` directory. The attribution identifies
Edym Pixels, the original filenames, the legacy resize, and display-only
permission without implying a general reuse license. Never overwrite
existing artwork; use a new versioned directory for later replacements.

| File | Dimensions | SHA-256 |
|------|------------|---------|
| `spr_256x256.png` | 256 x 256 original | `2d0fdbb12de9e09a83be6fd9742ddc40b838be1f8b2a7626b3930171f7112064` |
| `icon184x184.png` | 184 x 184 original | `d365cdb569ecd682bbfcdbb60835d6ba10b98cf129f576b1554fa9e4ef7e9416` |
| `logo-128.png` | 128 x 128 nearest-neighbor derivative of `spr_256x256.png` | Record in the private rollout manifest |

Set the following nonsecret values in the production `docker/.env` only
after provisioning and verifying the files:

```dotenv
MIRKLURK_LOGO_URL=/branding/2026-09/logo-128.png
MIRKLURK_LOGO_ICON_URL=/branding/2026-09/spr_256x256.png
MIRKLURK_FAVICON_URL=/branding/2026-09/icon184x184.png
```

Compose passes these through as `MW_LOGO_URL`, `MW_LOGO_ICON_URL`, and
`MW_FAVICON_URL`. Set both logo URLs together or leave both empty to retain
MediaWiki defaults. The favicon is independently optional. Paths must be
single-slash root-relative PNG paths with ASCII alphanumeric, underscore or
hyphen segments, and dots only within the filename; external origins,
queries, fragments and traversal are rejected by the runtime. Vector 2022
uses the exact 256-pixel icon at 50 x 50 display size and retains its normal
wiki title text. Legacy skins use the separate 128-pixel logo without
cropping the original; the favicon uses the supplied 184-pixel PNG.

Before acceptance, check anonymous HTTPS responses for all three PNGs
(`image/png`), dimensions and hashes against the staged files, the public
attribution, and the actual Vector/legacy logo and favicon HTML. Verify
application health and unchanged upload/edit policy, existing page revisions,
image records and database/backup container identities. Do not use a content
publisher, upload API, installer or schema updater for a branding rollout.

## First installation, before publishing

The image owns the account policy: public reading and self-registration,
registered-user editing, anonymous editing off, uploads off, QuestyCaptcha,
and rate limits. Email is disabled initially, so email-based password recovery
is unavailable. Follow the external repository's installation and content
licensing instructions; never upload raw game files or decompiled source.

Once deployment is approved and the merged production configuration is ready:

```bash
z /srv/homeserver/docker
docker compose config --quiet
docker compose up -d mirklurk-db
docker compose run --rm --no-deps --env MW_READ_ONLY= \
  --volume /srv/docker/data/mirklurk/secrets/MIRKLURK_ADMIN_PASSWORD:/run/secrets/MIRKLURK_ADMIN_PASSWORD:ro \
  mirklurk php /usr/local/lib/mirklurk/install.php \
  --admin WikiAdmin --password-file /run/secrets/MIRKLURK_ADMIN_PASSWORD
```

The installer refuses a nonempty schema. Follow the external repository's
current installation and API publishing documentation for content setup.
Do not re-import source pages over community edits. GitHub source content is
not a backup of the live wiki's users, revision history, or settings.

Start only `mirklurk` and `mirklurk-backup` after initialization and seeding.
The image's healthcheck is
`php /usr/local/lib/mirklurk/healthcheck.php`; it queries the local API and
database rather than merely checking an Apache process. It must be healthy
before the operator connects their reverse proxy to `http://mirklurk:80`.
Do not expose an uninitialized installer.

Check public HTTPS, redirects/cookies, anonymous read access, denied anonymous
edits/uploads, CAPTCHA-enforced registration, and authenticated editing before
declaring deployment complete. Verify both IP families where supported.
Reverse-proxy/TLS configuration is an operator-managed prerequisite, not
something this runbook automates.

## Content publication is separate

Normal operation sets the explicit empty literal `MW_READ_ONLY: ""` in the
canonical frontend. Do not use `.env` interpolation: a stale environment value
must not refreeze editing. Content is published separately by the wiki
repository's `tools/sync_wiki.py` API publisher after its reviewed main merge;
see its `docs/PUBLISHING.md`. The former freeze/native/operator page-release
flow is retired. A schema-neutral runtime rollout must not freeze editing.
A schema-adding upgrade instead requires a separately authorized interruption
with all writers stopped, as described below. Neither flow may run a content
import/publisher, merge a content PR, or retrieve publishing bot secrets.

## Backups and restore gate

`mirklurk-backup` runs as the host data owner in a read-only container with all
capabilities dropped. It has no Docker socket, no host privilege, no root DB
password, and no access to another service's files or database. It uses the
same digest-pinned MariaDB client version as the dedicated database.

It takes an InnoDB `--single-transaction` dump immediately and every six hours,
compresses it, checks gzip integrity and the presence of schema, and publishes
the file atomically. Empty/uninitialized databases are failures, not successful
backups. A failure keeps prior complete dumps, emits an error, makes the
container unhealthy, and retries after five minutes. Successful backups clear
the failure state; a success older than 6.5 hours is unhealthy.

There is one dump per UTC date under `daily/`, retained for seven days.
Sunday dumps also populate `weekly/`, retained for 28 days. Each successful
same-day run replaces that day's snapshot. Backup health is visible in Docker;
there is no additional offsite transfer or alerting credential in the sidecar.

The existing encrypted daily offsite job already includes
`/srv/docker/data/mirklurk/`, so dumps, wiki secrets, and images are covered
without modifying NixOS or rebuilding it. The live named MariaDB volume is
**not** backed up by that file sync; the SQL dumps are essential. Offsite
replication follows the existing daily schedule, not the six-hour dump cadence.

After installation, require a real dump and a successful restore into a
**new disposable database**, using the pinned client/server image. Compare
page/revision/user counts and known page text, then remove only the explicitly
named disposable restore resources. Never restore into the production DB as
a test. Script regression tests, gzip integrity, and an exit-zero offsite job
do not establish restoreability or remote backup integrity.

For recovery, restore SQL plus the matching runtime secrets and images with
the wiki offline and the matching application release, then validate before
publishing. The `WikiAdmin` password file records only the initial password;
after an in-wiki password change it is not the current credential.

## Controlled updates and domain moves

Application and database versions are pinned; update them deliberately with
a current backup, matching extension versions, the upstream MediaWiki update
procedure, and health/content checks. Verify required extension files and
configuration, including ParserFunctions, before pinning the new image's full
immutable ID. Verify the loaded runtime during the wiki-only rollout before
any separately authorized content publication.
The homeserver's normal daily build does not rebuild the wiki, perform schema
migrations, or pull the external wiki checkout. Record both repository commits
and the local image ID for each release. The existing generic deploy helper
does not build this pinned frontend or advance its image.

### DiscussionTools preparation (not authorized for activation)

**The existing `mirklurk-release.py deploy` is not a schema-upgrade procedure.**
It backs up and replaces the running app, then runs readiness checks and jobs;
it neither stops all writers before migration nor runs the schema updater.
Do not use that mode for this release, or start the new app before migrating.
Its successful `preflight` checks configuration/provenance, not schema readiness.

Preparation on 2026-10-01 left the canonical Compose pin and live app unchanged.
Only an immutable image and an online, restore-verified database backup were
prepared. The updater timer was active, its service inactive, the wiki writable,
and `mirklurk-sitemap` units not installed. These are observations, not a durable
writer guard: recheck immediately before any later authorized operation.

| Provenance | Immutable value |
|------------|-----------------|
| Reviewed wiki source | `493cffa19ffa403ff01ee8cedbfced200d89799f` |
| Prepared image | `sha256:b63347127089bf020df2f5f9b843acd6c0d1d34b15cca5f45aab9018630081b9` |
| Retention tag (not a deployment reference) | `mirklurk-wiki:release-493cffa19ffa` |
| Current rollback candidate | `sha256:b6904cf0bb2835fef6e629fa73032d5eb4555583d2c5fb4ae2c72a617f14aca3`, source `14ac05ff13918033105b6964a9c5f6d66c9ecb43` |
| Predecessor retention tag | `mirklurk-wiki:release-14ac05ff1391` |
| Build checkout | `/srv/docker/mirklurk-release-493cffa1.Gizir1/source`, clean detached exact source |

The build used `--pull=false`, the unchanged MediaWiki 1.43.9 base digest
listed below, and OCI source/revision labels. Image checks ran without a
network or production mounts/secrets. Runtime/configuration file hashes match
the source; ParserFunctions, Scribunto, PageImages, VisualEditor, TemplateData
and ConfirmEdit remain present alongside Echo, Linter and DiscussionTools.
Keep `$wgLinterParseOnDerivedDataUpdate = false`: DiscussionTools requires
Linter loaded, not an extra Parsoid parse for every links update.
The source's [main validation run](https://github.com/dantebarbieri/mirklurk-wiki/actions/runs/36929757800)
completed successfully for this exact SHA, including the disposable
DiscussionTools Docker smoke test and the existing publication workflow.
CI success does not authorize production migration or activation.

#### Online backup evidence and limitation

The established backup script ran once with a unique `BACKUP_DIR` beneath the
configured backup storage, without changing its scheduler or replacing the
ordinary daily snapshot. The retained dump is:

```text
/srv/docker/data/mirklurk/backups/predeploy-493cffa19ffa-20261001T2145Z/daily/mirklurk-2026-10-01.sql.gz
SHA-256: 8a841ee5537a61747e50ed2166f3f3d47d7573da64727f20e6866197f178dd3a
```

Created at 21:44:34-21:44:39 UTC, it is 23,829,039 bytes, mode `0600`, beneath
a private release backup directory. Gzip/schema checks passed. It restored
successfully into the pinned MariaDB 11.4.13 image with `--network none`,
`--skip-networking`, no published ports or host/named-volume mounts, and a
disposable tmpfs database. All 58 tables passed `mariadb-check`. Restored/live
counts matched before and after verification: 1,135 pages, 4,316 revisions,
7 users and 636 images; the `Items` latest revision (3379) and stored-text
SHA-256 also matched. The exact disposable container was removed; no dump,
credentials or artwork left the server.

**This is not proof of a single transactional snapshot of every table.**
Production contains 57 InnoDB tables and a MyISAM `searchindex` table.
`--single-transaction --skip-lock-tables` provides the InnoDB snapshot, but
cannot guarantee a consistent MyISAM search index while edits continue.
Successful restoration and matching counts do not remove that limitation.
Do not lock writers or convert tables during preparation. The eventual
authorized interruption must include a fresh final backup after every writer
is stopped. The preparation snapshot also cannot include later community edits.
The new dump resides within existing offsite coverage, but offsite replication
and remote restoreability were not verified by this local drill.

#### Required approval and migration sequence

The following is a **pending operator-reviewed sequence**, not authorization
to execute it. No new image pin accompanies this preparation.

1. Obtain new explicit approval for the interruption, writer/service controls,
   final backup, schema migration, pin merge and application replacement.
   Require exact-source CI success, retained images and a reviewed canonical
   pin/revision change. Pause the homeserver updater before merging that pin,
   require both updater units inactive, and hold the existing bounded Compose
   lock through the attended operation. A previous preflight is not a merge
   lock; do not enable auto-merge or rely on an inactive service alone.
2. Finish/coordinate wiki publication workflows and prevent new publication
   during the window. Identify and stop all wiki web/background writers,
   including the app, job runners, CLI maintenance and any sitemap job.
   No dedicated runner was observed during preparation, but re-enumerate.
   Stopping the updater alone is not a writer guard. Keep the DB and scoped
   backup client running; do not stop unrelated services or rebuild NixOS.
3. With writers confirmed stopped, take and verify a fresh final retained
   backup using the established client. Preserve matching images, branding
   and runtime secrets in protected storage. Reconfirm the reviewed
   configuration changes only the image/revision and preserves the live
   `https://mirklurk.wiki` origin, literal empty `MW_READ_ONLY`, mounts,
   proxy trust, networks, routes and access policy.
4. Run the new image's `php maintenance/run.php update --quick` **once in a
   one-off app container**, with `MW_READ_ONLY` explicitly cleared and the
   reviewed production Compose environment, DB network and secret-file
   mounts. Use the main Compose entry point, `--no-deps`, `--pull never`,
   `--rm`, and `--user www-data`; never start the new web app first.
   Check the updater exit status and required Echo/Linter/DiscussionTools
   tables. A failure leaves writers stopped for attended diagnosis, not an
   automatic retry, rollback or service restart.
5. Only after successful migration, recreate just `mirklurk` with
   `up -d --no-deps --no-build --pull never mirklurk` from the reviewed
   canonical main configuration. Check readiness, loaded old/new extensions,
   canonical routes, branding and preserved content. Then perform an
   explicitly authorized bounded purge of existing talk pages, and signed-in
   Reply/Add topic/notification checks. Do not reseed, upload assets,
   initialize all PageImages again, activate the reader sidebar or publish
   articles as part of this rollout.
6. Resume only the writers/schedules deliberately paused for this window,
   after acceptance. Record actual sampled interruption and final identities.
   Installing the absent sitemap timer is a separate OS-change decision.

Expect an outage from stopping web writers through the final backup, migration
and new-app readiness. The prior schema-neutral release's short restart time
is not an estimate for this upgrade; migration duration has not been rehearsed.

**Rollback after schema changes is not an image-only guarantee.** Retain the
predecessor, but inspect completed/partial migrations and establish compatibility
before considering it against the upgraded database. Prefer a forward fix when
safe. Restoring the matching pre-upgrade database requires separate explicit
approval, all writers stopped, and matching files/secrets; it discards writes
made after that snapshot. Never run an automatic DB restore, downgrade updater
or blindly apply the schema-neutral recovery instructions below.

### Visual editing and page-icon release (deployed predecessor)

**Do not merge until the operator has paused the updater.** A merged pin can
otherwise be activated by the 04:00 daily updater, without the release command.
A completed preflight or an expired lock does not protect a future merge.
Arrange a short, attended merge/activation window.

| Provenance | Immutable value |
|------------|-----------------|
| Reviewed wiki source | `14ac05ff13918033105b6964a9c5f6d66c9ecb43` |
| Candidate image | `sha256:b6904cf0bb2835fef6e629fa73032d5eb4555583d2c5fb4ae2c72a617f14aca3` |
| Retention tag (not a deployment reference) | `mirklurk-wiki:release-14ac05ff1391` |
| Live predecessor | `sha256:8f9e7aad4dff754cf3701c6ff2c056a08f51c6fbf865a6ef891ca31c2ee37aca`, source `7efcb77407a5e3d49f533525d7a0c5c71dafd0d2` (mobile and metadata release) |
| Unchanged base | `mediawiki:1.43.9@sha256:39a6503b8739f6aa58f8a458e9537258dd537f7cec7dd93c665bd3b43252d971` |
| Unchanged DB/client | `mariadb:11.4.13@sha256:70cc072b29b4a89ae07abb2d4da2c64678a7f2dfe092751bb51c87d67dc1338b` |

The source adds VisualEditor and TemplateData (mirklurk-wiki #36; shared-data
owner pages stay source-only) and PageImages per-page search/link-preview icons
(mirklurk-wiki #37). All three ship with MediaWiki 1.43; none adds database
tables. Both PRs passed full release CI, including the Docker smoke test.
The candidate was built on the target on 2026-10-01 from a clean detached
checkout at `/srv/docker/mirklurk-release-14ac05ff.Evoqtd/source`, with
`--pull=false` and OCI source/revision labels. Keep both images tagged against
the existing updater's dangling-image prune.

The sitemap directories were provisioned for the mobile release and are reused
unchanged. After the deploy command is accepted, populate PageImages' page
properties once and drain the queued jobs (no schema update):

```bash
docker exec --user www-data mirklurk php /var/www/html/maintenance/run.php \
  /var/www/html/extensions/PageImages/maintenance/initImageData.php
docker exec --user www-data mirklurk php /var/www/html/maintenance/run.php runJobs
```

Then verify, signed in: an ordinary article such as `Weather` offers **Edit**
(visual) and **Edit source**; a shared-data owner such as `Antidote` offers only
**Edit source** with the source-editing notice. Anonymous users see source
editing only. `Special:Search` shows item icons.

Source, content and runtime are separate states. This rollout **must not
publish/reseed/adopt content**, freeze edits, create accounts, run schema
updates, or change CAPTCHA, rights, proxy trust, secrets, images or branding.
Do not compare all live revisions to an old fixed snapshot: community edits
can legitimately advance while the runtime is prepared.

#### Pre-merge gate and preflight

Run these privileged steps in an attended operator shell shortly before merge,
not hours in advance. They do not stop the wiki. Never request a password in
chat or widen sudo policy for this procedure.

```bash
sudo systemctl stop docker-compose-update.timer
systemctl show docker-compose-update.timer docker-compose-update.service -p Id -p ActiveState
```

Require **both units inactive**. Stopping the timer does not stop an already
running update. If the service is active, wait for its normal completion and
recheck; do not kill it. If the rollout is deferred **before merging**, promptly
restart the timer with `sudo systemctl start docker-compose-update.timer`.
Stopping is intentionally not disabling/masking: a reboot can reactivate the
timer. Avoid reboot/NixOS activation/manual broad Compose commands during this
window; recheck state after any interruption. No unattended/perpetual lock.

The dedicated storage is outside Git. Both directories must be UID/GID 33
with mode `0755` or `2755`: `install -d -m 0755` can retain the shared parent's
setgid bit. This preserves group 33 inheritance without adding any read/write/
execute permission, so no corrective chmod is needed. Other special bits,
group/world write permission, unexpected ownership and symlinks are rejected.
Do not recursively chown the shared
parent or populate it from an old sitemap. `create_host_path: false` makes
missing provisioning a hard failure. The candidate must already be built and
tested; no build or image pull occurs during activation.

Set the reviewed values once in the operator shell:

```bash
source=14ac05ff13918033105b6964a9c5f6d66c9ecb43
image=sha256:b6904cf0bb2835fef6e629fa73032d5eb4555583d2c5fb4ae2c72a617f14aca3
previous=sha256:8f9e7aad4dff754cf3701c6ff2c056a08f51c6fbf865a6ef891ca31c2ee37aca
```

From a clean checkout of the exact proposed homeserver PR, run:

```bash
nix shell nixpkgs#python3 --command python3 docker/scripts/mirklurk-release.py preflight \
  --checkout "$PWD" --source "$source" --image "$image" --previous-image "$previous"
```

The standard-library Python helper reads the canonical `.env` without printing
it and acquires the same existing `/run/lock/homeserver-compose.lock` for at
most 30 seconds. It checks the explicit source and image against the reviewed
Compose pin/revision and image labels, local predecessor, unchanged runtime
environment/mounts/networks, healthy app/DB/backup, correct public origin,
storage permissions and headroom (2 GiB available RAM, 5 GiB free disk,
one-minute load below logical CPU count). Preflight does not pull, back up,
refresh, publish or restart anything. It releases its lock on exit.

#### After the operator merges

Keep the timer paused. Bootstrap the new helper into clean canonical `main`
under the existing lock; this pull alone does not activate containers:

```bash
z /srv/homeserver
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
bash -c 'exec 9</run/lock/homeserver-compose.lock; flock -x -w 30 9 && git pull --ff-only origin main'
nix shell nixpkgs#python3 --command python3 docker/scripts/mirklurk-release.py deploy \
  --source "$source" --image "$image" --previous-image "$previous"
```

The deploy command locks, verifies the updater is paused, fast-forwards clean
canonical `main` again **under that same lock**, and reruns preflight. If the
helper itself changed during the pull, it refuses activation until rerun. It
takes a fresh consistent SQL dump through the existing scoped backup client
before invoking exactly:

```bash
docker compose --project-name compose --project-directory /srv/homeserver/docker \
  --env-file /srv/homeserver/docker/.env --file /srv/homeserver/docker/docker-compose.yml \
  up -d --no-deps --no-build --pull never mirklurk
```

Only the app is recreated; DB, backup, ddclient, proxy and other container IDs
must remain unchanged. **Expect a brief interruption with one app container.**
In-flight requests/edits can fail; this is not zero downtime. The helper reports
sampled public API failures and an activation-to-readiness upper bound rather
than claiming exact outage precision. It checks API/short paths, device-width
viewport, canonical metadata, ResourceLoader and branding; then processes a
bounded batch of already-pending jobs and refreshes the native sitemap.
No publication or revision rollback is part of this command. Repeating an
accepted deployment checks/refreshes it without recreating the app again.

The SQL backup is atomic, `--single-transaction`, and gzip/schema-checked using
the established backup mechanism. Previous restore drills remain the evidence
for restoreability; this runtime-only release does not modify images/branding
or run an expensive production restore test. Existing offsite coverage includes
the new sitemap directory (which is derived data, not a content backup).

After acceptance, record canonical homeserver HEAD, running image, observed
availability, sitemap freshness and preserved service IDs, then restore normal
scheduling and verify the next run:

```bash
sudo systemctl start docker-compose-update.timer
systemctl list-timers docker-compose-update.timer --no-pager
```

#### Sitemap schedule and freshness

The image uses core `generateSitemap` behind its reviewed guarded wrapper, not
a new sitemap implementation. Only public main/category namespaces are
enumerated; redirects and author noindex pages are excluded. Generation runs
as `www-data` after pending jobs, stages outside the public directory and
atomically replaces the index after publishing unique shards.

The NixOS `mirklurk-sitemap` oneshot/timer runs daily at **05:30** and after a
missed schedule, using the same Compose lock and the same helper's
`refresh-sitemap` mode. Nonzero exits use the existing `ntfy-failure@` handler.
Every refresh checks local index age below five minutes plus anonymous
robots/index/all-shard responses and canonical URLs. An absent first sitemap
is failure, never an empty-success placeholder.

Install the schedule only after the merged runtime is accepted, at the next
operator-reviewed NixOS switch:

```bash
sudo nixos-rebuild switch
systemctl list-timers mirklurk-sitemap.timer --no-pager
sudo systemctl start mirklurk-sitemap.service
journalctl -u mirklurk-sitemap.service -n 30 --no-pager
```

A full NixOS switch can apply **other pending OS changes**; it is not part of
the app's narrow activation and must not be run blindly just to install the
timer. Until that switch, manually run the refresh daily and after content
releases/significant edits:

```bash
z /srv/homeserver
nix shell nixpkgs#python3 --command python3 docker/scripts/mirklurk-release.py refresh-sitemap
```

Inspect the journal/ntfy and the index file's mtime; more than 26 hours without
a successful refresh needs investigation (a stopped timer cannot send an
OnFailure alert). Keep old shards at least a day for cached indexes. No
automatic cleanup is needed for this rollout; later cleanup must select only
unreferenced `sitemap-*.xml` in this dedicated `public` directory, never shared
paths. The existing proxy forwards `location /` transparently; verify anonymous
`/robots.txt`, `/sitemap.xml` and root `/sitemap-*.xml` after activation without
changing DNS/TLS/CDN/access policy.

#### Failure and routing-compatible recovery

Failures are nonzero; **do not automatically restart the updater after a
failed activation**. Inspect the wiki's scoped logs locally. A failed sitemap
refresh leaves the previous complete index intact; fix/retry it without
recreating an already-healthy candidate. A missing initial index is still a
release blocker. A failed app needs an attended runtime recovery, not a
database/content restore.

The live `8f9e7aad...` mobile/metadata image is the immediate predecessor and
includes the sitemap wrapper. Recovering to it needs only a reviewed pin
restore; existing VisualEditor/PageImages data are harmless page properties.
The retained `ea903376...` image also supports public `/w/` links. The older `5e9c67b6...` pre-short-URL image is **not**
a safe fallback after public 301s. Use a reviewed canonical recovery commit
that restores the predecessor image **and matching source label**, preserves
origin/read-write/access policy and the storage mount, and defers its sitemap
schedule (the old image lacks the wrapper). Pull that merged commit under the
same lock and run the app-only `up` command above, then verify old/new URLs,
API, branding and unaffected service IDs before resuming the updater.
Do not make raw local pin edits that the next updater undoes, reverse the
public redirects, restore the DB, or overwrite newer community content.

The helper deliberately does not manufacture a recovery commit or auto-rollback.
If reviewed recovery cannot be made promptly, escalate while keeping the
updater paused and explicitly owned; never call that unresolved state complete.
GHCR publishing/image-pin automation is deferred, not a prerequisite here.

### Routing contract retained from the short-URL release

The image sets articlepath `/w/$1` with empty scriptpath. Its real Apache
port-80 vhost uses `AllowEncodedSlashes NoDecode` and adds fixed-`index.php`
rules only for `/w`, `/w/...` and `/`; it never reconstructs `?title=` from
a decoded path. The base image's existing non-file/non-directory fallback
also remains unchanged; the new rules are not a claim that Apache rejects
every other path. MediaWiki handles missing article titles.
Root `/api.php`, `/rest.php` with path-info, `/load.php`, `/resources`,
`/skins` and `/images` remain at their existing paths.

Plain legacy article-view GET/HEAD requests receive a 301 to `/w/...`.
Extra/duplicate parameters, special pages, actions, history, oldid/diff,
POSTs, login/search and native wiki redirects retain upstream behavior.
The root/empty article path uses MediaWiki's configured main page.

Scoped nonsecret NPM configuration inspection on 2026-09-30 found
`mirklurk.wiki` forwarding `location /` to `http://mirklurk:80` through
`proxy_pass $forward_scheme://$server:$port$request_uri`, with existing
Host/protocol/client-IP headers. No `/w` stripping or title rewrite was found.
Recheck this prerequisite before activation: preserve the original encoded
path, query, method and REST path-info. Any needed proxy correction is an
operator-owned, separately approved step, not part of this PR.
No DNS, certificate, domain or CDN change is required.

No new `.env` variable is needed. `MIRKLURK_SERVER_URL` already supplies
`MW_SERVER_URL=https://mirklurk.wiki`; do not switch to the old-domain fallback.
Preserve literal `MW_READ_ONLY: ""`, authentication/CAPTCHA/rate-limit and
upload policies, Scribunto, database/secrets/images/branding mounts, networks
and proxy trust. Do not overwrite `LocalSettings.php`, run an installer or
schema updater, publish/import content, rename articles or restore the DB.

#### Separately authorized cache refresh

Old parser output can still contain long links. This image has no deployment
environment setting for `$wgCacheEpoch`: do not patch/bind-mount settings or
invent an environment variable. After activation is healthy, obtain separate
approval for a bounded, named page set and use MediaWiki's supported
**POST `/api.php` `action=purge`** with `titles` and `format=json`.
Check each per-title result for `purged` or errors, then fetch those pages to
regenerate output. Do not add forced recursive/link updates, run a blanket
job-queue drain, edit pages, or clear session storage. Confirm fresh article,
category and template-generated links use `/w/`.

If any proxy/CDN HTML cache is enabled, separately authorize invalidating only
the affected wiki HTML/redirect entries, including earlier `/w/...` main-page
responses and root redirects. Do not flush unrelated caches or change proxy
configuration. Record remaining stale pages rather than claiming a bounded
purge refreshed the entire wiki.

Change `MIRKLURK_SERVER_URL` for a future domain migration and update the
Homepage URL alongside the operator-managed proxy. Database, image paths,
and page content are not hostname-dependent. The sibling
`seedfinder.mirklurk.danteb.com` is reserved for a separate future service;
this integration does not create it.
