# Hytale authentication and updates

The `hytale-server` service uses the persistent `compose_hytale-server` volume.
Do not remove that volume, its worlds, or `/data/.machine-id` during recovery.
Use the main Compose entry point in `/srv/homeserver/docker`.

## Unattended updates

Hytale participates in the normal nightly Docker image updater; it no longer
has an opt-in Compose profile. Game updates are managed separately by Hytale's
built-in updater, using the image's `HYTALE_NATIVE_UPDATES` runner:

- Check the stable `release` patchline every hour.
- Download available updates and apply them only when no players are online
  (`Update.AutoApplyMode=WhenEmpty`).
- Back up worlds and configuration before applying. Automatic backups are
  enabled at `/data/backups`; the server's default retention is five backups
  and five archived backups.
- On update exit code 8, the image installs the staged binaries/assets and
  restarts Java without replacing worlds, configuration or authentication.
- Allow 120 seconds for graceful container shutdown.

`HYTALE_AUTO_DOWNLOAD=true` still provisions missing game files on a fresh
volume. `HYTALE_AUTO_UPDATE=false` disables only the **startup downloader's**
update check, not game updates. Do not enable both update mechanisms or set
`HYTALE_DISABLE_UPDATES=true`. An expired downloader login must not block an
already-provisioned server from starting or updating through its own login.

The native updater requires an image with native-update support (the recovery
used wrapper 1.3.0). Its runner creates `/data/start.sh` for Hytale's layout
check and retains previous binaries at `/data/updater/image-backup/previous`.
Keep an independent full-volume backup before a major upgrade: rolling back
only the Docker image does not roll back migrated worlds or game files.

## Downloader versus game-server authentication

There are two independent authentication stages:

1. The official downloader uses `/data/.hytale-downloader-credentials.json`
   to provision missing files. It is not used for routine native updates.
2. The game server uses its own OAuth login for player connections **and native
   update downloads**. Compose enforces encrypted persistence in
   `/data/server/auth.enc`. Keep `/data/server/config.json`, any
   `/data/server/auth.key`, and `/data/.machine-id` along with it.

Routine restarts and container recreation reuse the saved server login, and
the server refreshes its tokens while running. This does not make a grant
permanent: revocation, provider expiry, or a long offline period can still
require the owner to authorize again. Never copy credentials into this repo,
print their contents, or put tokens in Compose environment variables.

## Server login and status

From the main Compose directory:

```bash
z /srv/homeserver/docker
docker compose up -d hytale-server
docker compose exec -T hytale-server hytale-cli auth status
docker compose logs --since 2m hytale-server
```

If the saved server login is expired or missing:

```bash
docker compose exec -T hytale-server hytale-cli auth login
docker compose logs --since 2m hytale-server
```

Open the official `https://accounts.hytale.com/device` URL and enter the
displayed code yourself. `auth login` queues encrypted persistence before the
device login. If Hytale offers multiple profiles, use
`hytale-cli auth select <name-or-number>`.

Confirm both authentication and updates, reading the logs after each command:

```bash
docker compose exec -T hytale-server hytale-cli auth status
docker compose exec -T hytale-server hytale-cli send "/update check"
docker compose exec -T hytale-server hytale-cli send "/update status"
```

The CLI queues console commands; its exit status alone is not proof of
authentication. Docker health checks prove the process and UDP listener exist,
not that players can authenticate. After recovery, recreate only Hytale and
confirm that authentication returns without another device login:

```bash
docker compose up -d --force-recreate hytale-server
```

Clients connect to `danteb.com:5205` (UDP). Keep authenticated mode enabled.

## Downloader recovery (fresh provisioning only)

An `invalid_grant` error while fetching the game-assets manifest is a
**downloader** failure. The server's `/auth` command cannot renew that separate
grant. Only recover it when provisioning/downloading through the downloader,
not to repair the running server's native updater.

Stop the already-failing service during reauthorization to avoid its restart
loop. Preserve the old credential file as a private backup; never print its
contents, copy it into this repository, or paste tokens into chat.

The installed downloader supports `-credentials-path`, `-skip-update-check`
and `-print-version`. Run it as a one-off Compose container with the same data
volume, using a **new, nonexistent credential filename in a mode-700 directory**
and a restrictive `umask 077`. The entrypoint is:

```text
/data/.hytale-downloader/hytale-downloader
```

Request `-print-version` rather than a download while authorizing. Follow its
official browser URL/device-code instructions yourself. Only after successful
authentication and a successful version query should the new credential file
replace the expired one; retain the private backup, use mode 600, and preserve
the container user's ownership. Failed or canceled authorization must leave
the original credential file and game data untouched.

Then provision the files and start only `hytale-server` using the main Compose
configuration. A separate game-server login may be needed. Do not switch to
offline authentication or disable native updates to hide an authentication error.

Upstream references:

- [Official server manual: auto-updating](https://support.hytale.com/hc/en-us/articles/45326769420827-Hytale-Server-Manual)
- [Image authentication](https://github.com/Hybrowse/hytale-server-docker/blob/main/docs/image/authentication.md)
- [Image native updates](https://github.com/Hybrowse/hytale-server-docker/blob/main/docs/image/upgrades.md)
- [Troubleshooting](https://github.com/Hybrowse/hytale-server-docker/blob/main/docs/image/troubleshooting.md)
