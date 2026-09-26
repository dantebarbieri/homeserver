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

Both bind mounts use `create_host_path: false`. Persistent images remain
available for later explicitly approved CLI imports even while browser
uploads are disabled. Game assets stay outside Git.

`MIRKLURK_TRUSTED_PROXY_CIDRS` maps to the image's
`MW_TRUSTED_PROXY_CIDRS`. Use the reverse proxy's actual container-side
address(es), preferably `/32` and `/128`, not `0.0.0.0/0`, `::/0`, or the
entire shared web-service network. Verify forwarding and rate-limit behavior
with that configuration. Recheck the value if the proxy's address changes.

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

The installer refuses a nonempty schema. Build the fresh seed XML using the
external repository's `tools/build_wiki.py --fresh` flow and follow its guarded
fresh-only import procedure **before** enabling public access. Do not regularly
re-import source pages over community edits. GitHub source content is not a
backup of the live wiki's users, revision history, or settings.

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

## Published wiki edit freeze

The canonical frontend currently sets the literal `MW_READ_ONLY` reason
`MirkLurk content update in progress`. This temporary edit freeze survives
ordinary Compose recreation and cannot be cleared through `.env`. Readers
remain online; the images mount and normal cache/thumbnail writes stay writable.
For approved publication, follow the external repository's guarded procedure
in a one-off maintenance container with `MW_READ_ONLY` cleared for that process
only. Preserve existing edits, history, accounts, and original images. Clear
the frontend freeze in a separate reviewed homeserver change **only after**
the coordinator and host operator verify successful publication; never
automatically clear it on failure.

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
any import or content write.
The homeserver's normal daily build does not rebuild the wiki, perform schema
migrations, or pull the external wiki checkout. Record both repository commits
and the local image ID for each release. The existing generic deploy helper
does not build this pinned frontend or advance its image.

Change `MIRKLURK_SERVER_URL` for a future domain migration and update the
Homepage URL alongside the operator-managed proxy. Database, image paths,
and page content are not hostname-dependent. The sibling
`seedfinder.mirklurk.danteb.com` is reserved for a separate future service;
this integration does not create it.
