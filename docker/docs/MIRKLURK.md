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
| Public URL | `MIRKLURK_SERVER_URL`, initially `https://wiki.mirklurk.danteb.com` |
| Proxy trust | `MIRKLURK_TRUSTED_PROXY_CIDRS`, verified proxy addresses only |
| Database | `mirklurk-db:3306`, database/user `mirklurk`, named volume `compose_mirklurk-db` |
| Images | `${DATA}/mirklurk/images` -> `/var/www/html/images` |
| Branding | `${DATA}/mirklurk/branding` -> `/var/www/html/branding` (read-only) |
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
flow is retired. A runtime rollout must not freeze editing, run a content
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

### Branding runtime-only release

The frontend pin adds the optional logo/favicon runtime settings described
above, retaining Scribunto with its bounded `luastandalone` engine.
MediaWiki, database, authentication, editing, upload and network policies
are unchanged. No schema migration or content publication is required.

| Provenance | Immutable value |
|------------|-----------------|
| Wiki runtime source | `cc7dd6552ce122bc32b0149f5cc338a57fda7396` from [wiki PR 27](https://github.com/dantebarbieri/mirklurk-wiki/pull/27); runtime files only, not a content publication |
| Base image | `mediawiki:1.43.9@sha256:39a6503b8739f6aa58f8a458e9537258dd537f7cec7dd93c665bd3b43252d971` |
| Frontend image | `sha256:5e9c67b606c1e52b964359b42fa71f9027261ceb816e0791fd97b3d53356c4dc` |
| Retained rollback image | `sha256:adf9aa9bfcb04911ce8a814581784106224cd6db05e21a4c8dc2f9d398afbe8d` (`mirklurk-wiki:scribunto-84b8b6c`) |

The new local image has source/revision OCI labels and tag
`mirklurk-wiki:branding-cc7dd65`; Compose uses only its exact image ID.
The Dockerfile and `.dockerignore` copy only `LocalSettings.template.php`,
`mirklurk-runtime.php`, `install.php` and `healthcheck.php`. No source wiki
pages, templates, modules or publishing tools are installed by this build.

For an explicitly approved runtime rollout, use an isolated checkout of the
reviewed immutable commit rather than changing a shared external checkout.
Build and validate the image on the target host before merging its reviewed
homeserver pin. Preserve the old image, take a fresh consistent SQL dump and
images/branding backup, and capture frontend mounts/policy and database/backup
container identities. Coordinate with the existing updater through
`/run/lock/homeserver-compose.lock` (an exclusive `flock` on a read-only
descriptor is sufficient; do not replace the lock file).

Fast-forward the clean canonical checkout to the reviewed main merge and,
while holding that lock, use the main Compose entrypoint only:

```bash
z /srv/homeserver/docker
docker compose config --quiet
docker compose up -d --no-deps --no-build --pull never mirklurk
```

Do not restart the database or backup sidecar, run `update.php`, install/import
content, or change the existing images/secret mounts. Require healthy Docker
and public HTTP/API responses, unchanged existing page revisions/images/accounts and
access policy, Scribunto plus canonical Module namespace 828 in siteinfo,
and the `Scribunto` content model in edit paraminfo. Verify real Lua through
`scribunto-console` with unsaved module text and an exact expected result;
this uses only an ephemeral console cache and does not save a module.
Do not use publisher `--apply` as a runtime test. Verify the branding markup,
anonymous image responses and original hashes described above; content
merge/publication remains a separate decision.

If runtime acceptance fails, restore only the frontend to the retained image,
preserving its mounts and policy; no database restore is part of this rollback.
Reconcile the rollback through a reviewed pin revert on canonical main. Any
emergency image override is temporary, must be reported, and must be removed
once the tracked pin matches the restored service.

Change `MIRKLURK_SERVER_URL` for a future domain migration and update the
Homepage URL alongside the operator-managed proxy. Database, image paths,
and page content are not hostname-dependent. The sibling
`seedfinder.mirklurk.danteb.com` is reserved for a separate future service;
this integration does not create it.
