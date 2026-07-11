# RomM

RomM provides the central catalogue and authenticated download service for
legally owned ROM backups. The server stores the library on the RAID and exposes
only the RomM web application through Nginx Proxy Manager.

## Storage

RomM uses the recommended top-level `roms/` and `bios/` layout:

```text
/data/shared/games/romm/library/
|-- roms/
|   |-- gba/
|   |   `-- example.gba
|   `-- snes/
|       `-- example.sfc
`-- bios/
    |-- gba/
    `-- ps/
```

Platform directory names must match a
[supported RomM platform slug](https://docs.romm.app/latest/platforms/supported-platforms/).
RomM creates this structure automatically when the first files are uploaded
through the web UI.

Before starting the stack, create the bind-mount directories with ownership
matching the default RomM container user:

```bash
sudo install -d -o 1000 -g 1000 \
  /data/shared/games/romm/library/{roms,bios} \
  /srv/docker/data/romm/{resources,redis-data,assets,config}
```

The MariaDB data is stored in the Docker-managed `romm-db` volume. Uploaded
saves, save states, screenshots, and other user assets are stored under
`/srv/docker/data/romm/assets`.

## Import the existing Windows library

The source collection is `D:\iCloudDrive\ROMs`. Its current logical size is
approximately 58 GiB with more than 15,000 files, but the ROMs are iCloud
placeholders rather than locally hydrated files. In File Explorer, right-click
the `ROMs` directory and select **Always keep on this device**, then wait for
iCloud Drive to finish before staging or transferring anything.

Confirm that no eligible files remain offline:

```powershell
$files = Get-ChildItem 'D:\iCloudDrive\ROMs' -File -Recurse -Force
@($files | Where-Object {
    $_.Attributes -band [System.IO.FileAttributes]::Offline
}).Count
```

The result must be `0`. The source directories map to RomM's canonical slugs:

| Source directory | RomM directory |
|---|---|
| `Arcade` | `arcade` |
| `GameBoy` | `gb` |
| `GameBoy Advance` | `gba` |
| `GameBoy Color` | `gbc` |
| `N64` | `n64` |
| `NDS` | `nds` |
| `NES` | `nes` |
| `SNES` | `snes` |

`GameBoy`, `GameBoy Color`, and `NES` currently use region and category
subdirectories. RomM does not yet support arbitrary platform-level subfolders
([upstream issue](https://github.com/rommapp/romm/issues/2050)), so the migration
must flatten those files into the corresponding platform directory. The staging
script performs that normalization, rejects filename collisions, and excludes
the old PNG, JPEG, MP4, XML, DAT, SQLite, and text metadata caches. RomM will
fetch fresh metadata and artwork.

From the repository root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stage-romm-library.ps1
```

The normalized collection is written to `D:\RomM-Staging\roms`. Existing staged
files with the expected size are skipped, so the command is safe to rerun.

Use rclone over SFTP for a resumable transfer instead of `scp`:

```powershell
winget install --id Rclone.Rclone --exact
rclone config
```

Create an SFTP remote named `homeserver` with host `192.168.50.100`, user
`danteb`, port `28`, key file
`C:\Users\Dante\.ssh\id_ed25519_homeserver`, and
`C:\Users\Dante\.ssh\known_hosts` as the known-hosts file. This unencrypted key
has already been verified against the server and is compatible with rclone's
native SFTP backend. After the RomM directories exist on the server:

```powershell
rclone copy 'D:\RomM-Staging\roms' `
  'homeserver:/data/shared/games/romm/library/roms' `
  --progress --transfers 4 --checkers 8

rclone check 'D:\RomM-Staging\roms' `
  'homeserver:/data/shared/games/romm/library/roms' `
  --one-way
```

Remove `D:\RomM-Staging` only after `rclone check` succeeds and RomM completes
its first scan.

## Environment

Add these values to `/srv/homeserver/docker/.env`. Generate each secret
separately; do not reuse one value for multiple settings.

```bash
openssl rand -hex 32 # ROMM_DB_ROOT_PASSWORD
openssl rand -hex 32 # ROMM_DB_PASSWORD
openssl rand -hex 32 # ROMM_AUTH_SECRET_KEY
```

Hasheous metadata matching is enabled without an API key. The optional
ScreenScraper, SteamGridDB, and RetroAchievements credentials are documented in
the [RomM metadata provider guide](https://docs.romm.app/latest/getting-started/metadata-providers/).

Keep `ROMM_AUTH_SECRET_KEY` stable. Changing it invalidates active sessions,
and invite links. Client API tokens are stored independently and must be
revoked explicitly.

## Start and initialize

Always use the main Compose entry point so RomM joins the same `proxy` network
as Nginx Proxy Manager:

```bash
z /srv/homeserver/docker
docker compose up -d romm
docker compose logs -f romm romm-db
```

After the proxy host is configured, open `https://romm.danteb.com`, complete the
setup wizard, and create the native administrator account. Use a strong, unique
password. Create separate accounts for other users so saves and client tokens
remain isolated.

Upload files through the web interface or place them in the RAID library, then
start a library scan in RomM. Files copied directly into the library trigger a
rescan because filesystem-change rescanning is enabled.

Native authentication is the only authentication layer for this deployment.
Do not enable kiosk mode or unauthenticated download endpoints. RomM stores
passwords with bcrypt, protects browser requests with CSRF middleware, and
issues scoped, revocable API tokens to clients.

## Nginx Proxy Manager

Create a proxy host with these settings:

| Setting | Value |
|---|---|
| Domain | `romm.danteb.com` |
| Scheme | `http` |
| Forward hostname | `romm` |
| Forward port | `8080` |
| Cache assets | Off |
| Block common exploits | On |
| WebSockets support | On |
| SSL | Let's Encrypt, Force SSL, HTTP/2 |
| HSTS | Enable after confirming TLS works |

Add this to the proxy host's **Advanced** configuration:

```nginx
proxy_max_temp_file_size 0;
```

This prevents Nginx Proxy Manager from buffering bulk and multi-disc downloads
to a temporary file. No router port, NixOS firewall rule, or Cloudflare record
is required; the existing HTTPS proxy and wildcard DNS cover the service.

## Browser downloads

Sign in at `https://romm.danteb.com`, browse or search the library, and download
only the selected game. RomM also supports browser play through EmulatorJS, but
browser play is optional and is not required for the download workflow.

For scripts and compatible clients, create a scoped Client API Token in the
user account instead of storing the account password. Revoke a token when a
device is retired or lost.

## Steam Deck

[decky-romm-sync](https://github.com/danielcopper/decky-romm-sync) is a
community-maintained Decky Loader plugin for RomM 4.9.0 or newer. It downloads
games on demand, adds them to Steam as non-Steam shortcuts, launches them
through RetroDECK, and can synchronize saves through each user's RomM account.
It is not maintained by the RomM project, so review its releases before
upgrading either component.

Prerequisites:

1. Install [RetroDECK](https://retrodeck.net/).
2. Install [Decky Loader](https://decky.xyz/).
3. Download the latest `decky-romm-sync.zip` from the
   [plugin releases](https://github.com/danielcopper/decky-romm-sync/releases).
4. Follow the plugin's
   [current installation guide](https://danielcopper.github.io/decky-romm-sync/user-guide/getting-started/).
5. Connect to `https://romm.danteb.com` using the device-pairing flow or a
   dedicated scoped client token.

The plugin is pre-1.0 and is not yet in the Decky Store. Its documented manual
installation currently requires Decky Developer Mode.

## Updates and recovery

RomM tracks the `latest` stable image and is updated by the normal homeserver
update workflow. Before a major RomM upgrade, review its release notes.

The NixOS daily database backup writes a consistent MariaDB dump to
`/data/automated-backups/mariadb/daily/`, rotates Sunday copies into `weekly/`,
and includes both directories in the normal encrypted offsite sync.

To restore a dump into an empty `romm` database:

```bash
z /srv/homeserver/docker
gunzip -c /data/automated-backups/mariadb/daily/romm-db-YYYY-MM-DD.sql.gz \
  | docker exec -i romm-db sh -c \
      'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -u root "$MARIADB_DATABASE"'
```

Stop `romm` while restoring so it cannot write concurrently.
`/srv/docker/data/romm` is included in the existing daily offsite sync. The ROM
library under `/data/shared/games/romm/library` is not currently copied offsite;
protect it separately if the original backups cannot be recreated.

To inspect startup, scan, or authentication failures:

```bash
z /srv/homeserver/docker
docker compose logs --tail=200 romm romm-db
```

RomM does not acquire games. Supply only ROMs and firmware that you are legally
entitled to store and use.
