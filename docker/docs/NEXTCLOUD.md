# Nextcloud Setup

Nextcloud provides self-hosted cloud storage with file sync, sharing, calendars, contacts, and more — a Google Drive / Dropbox alternative you own.

**Components:**
- **Nextcloud** — Main application server (Apache variant with built-in web server)
- **PostgreSQL** — Database backend
- **Redis** — Memory cache and transactional file locking
- **Cron** — Dedicated container for background job execution

## Generating Secrets

The Nextcloud stack requires one secret stored in `.env`:

- `NEXTCLOUD_DB_PASSWORD` — PostgreSQL password for the Nextcloud database

Generate it using one of these methods:

**openssl (recommended):**
```bash
openssl rand -base64 32
```

**pwgen:**
```bash
pwgen -s 48 1
```

**/dev/urandom:**
```bash
tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
```

Add the generated value to your `.env`:
```bash
NEXTCLOUD_DB_PASSWORD=<generated-password>
```

You'll also need to set an initial admin password:
```bash
NEXTCLOUD_ADMIN_USER=admin
NEXTCLOUD_ADMIN_PASSWORD=<choose-a-strong-password>
```

> **Note:** `NEXTCLOUD_ADMIN_USER` and `NEXTCLOUD_ADMIN_PASSWORD` are only used on the very first startup to create the admin account. After initial setup, changing these env vars has no effect — manage users through the Nextcloud web UI instead.

## Configuration

### Hostname

Set your Nextcloud hostname in `.env`:
```bash
NEXTCLOUD_HOSTNAME=cloud.example.com
```

> **Convention:** The standard subdomain for Nextcloud is `cloud` (e.g., `cloud.example.com`). This is the most widely adopted convention in the Nextcloud community and official documentation.

### Data Directory

User files are stored on the RAID array at `${RAID}/nextcloud`, mounted as `/data` inside the container. This is configured via the `NEXTCLOUD_DATA_DIR` environment variable in the compose file.

Application files (PHP code, config, custom apps) live at `${DATA}/nextcloud/html`.

### Trusted Domains

Nextcloud rejects requests whose HTTP `Host` header doesn't match a trusted domain, returning HTTP 400. Two domains must be trusted:

- **External hostname** (e.g., `cloud.example.com`) — for browser and client access
- **Internal Docker hostname** (`nextcloud`) — for other containers on the Docker network (e.g., Homepage widgets)

The compose file sets both via `NEXTCLOUD_TRUSTED_DOMAINS`, but this **only takes effect on first install**. To view or modify trusted domains on a running instance:

```bash
# List current trusted domains
docker exec -it --user www-data nextcloud php occ config:system:get trusted_domains

# Add a domain at a specific index (check existing indices first to avoid overwriting!)
docker exec -it --user www-data nextcloud php occ config:system:set trusted_domains <index> --value=<domain>
```

> **⚠️ Warning:** Each index holds one domain. Setting an existing index **silently overwrites** the previous value. Always list current domains first to find the next available index.

## Initial Setup

1. **Create data directories:**
   ```bash
   mkdir -p ${DATA}/nextcloud/html
   mkdir -p ${RAID}/nextcloud
   chown -R 33:33 ${RAID}/nextcloud
   ```
   > **Note:** The Nextcloud container runs as `www-data` (uid 33). The data directory must be writable by this user or installation will fail with "Cannot create or write into the data directory".

2. **Set your secrets** in `.env` (see [Generating Secrets](#generating-secrets)):
   ```bash
   NEXTCLOUD_HOSTNAME=cloud.example.com
   NEXTCLOUD_DB_PASSWORD=<generated-password>
   NEXTCLOUD_ADMIN_USER=admin
   NEXTCLOUD_ADMIN_PASSWORD=<choose-a-strong-password>
   ```

3. **Start the stack:**
   ```bash
   docker compose -f compose.nextcloud.yml up -d
   ```

4. **Wait for first-run initialization.** Nextcloud takes 1–3 minutes on first startup to install the database schema and configure itself. Monitor progress:
   ```bash
   docker logs -f nextcloud
   ```
   Wait until you see `AH00094: Command line: 'apache2 -D FOREGROUND'` indicating Apache is ready.

5. **Verify trusted domains.** Confirm both the external hostname and internal Docker hostname are trusted:
   ```bash
   docker exec -it --user www-data nextcloud php occ config:system:get trusted_domains
   ```
   You should see your external hostname (e.g., `cloud.example.com`) and `nextcloud`. If either is missing, add it at the next available index (see [Trusted Domains](#trusted-domains)):
   ```bash
   docker exec -it --user www-data nextcloud php occ config:system:set trusted_domains 2 --value=nextcloud
   ```

6. **Set background jobs to Cron.** After the first login, go to **Administration Settings** → **Basic settings** → set Background jobs to **Cron**. The `nextcloud_cron` container handles execution automatically.

7. **Resolve first-run warnings.** The Administration → Overview page will show several warnings after a fresh install. Run these commands to resolve them:

   **Fix missing database indices:**
   ```bash
   docker exec -it --user www-data nextcloud php occ db:add-missing-indices
   ```

   **Run mimetype migrations:**
   ```bash
   docker exec -it --user www-data nextcloud php occ maintenance:repair --include-expensive
   ```

   **Create a local config file** at `${DATA}/nextcloud/html/config/local.config.php` to set the maintenance window, phone region, and local memory cache:
   ```php
   <?php
   $CONFIG = [
     'maintenance_window_start' => 8,         // 3:00 AM CDT / 2:00 AM CST
     'default_phone_region' => 'US',           // ISO 3166-1 country code
     'memcache.local' => '\OC\Memcache\APCu',
   ];
   ```

   > **Informational notices you can safely ignore:**
   > - **AppAPI deploy daemon** — Only needed for External Apps (ExApps). Safe to ignore, or disable the AppAPI app in **Administration Settings** → **Apps** if you don't plan to use ExApps.
   > - **Two-factor authentication** — Nextcloud recommends enforcing 2FA but it's optional. Configure it in **Administration Settings** → **Security** when ready.
   > - **Email server** — Configure SMTP in **Administration Settings** → **Basic settings** when you're ready to set up email notifications.
   > - **Server identifier** — Only relevant for multi-server deployments. Ignore for single-server setups.

## Reverse Proxy (Nginx Proxy Manager)

### DNS Record

If you have a wildcard record (`*.example.com`), the subdomain `cloud.example.com` will resolve automatically. Otherwise, create a record:
```
cloud.example.com    CNAME    example.com
```

### Create Proxy Host

In Nginx Proxy Manager, add a new proxy host:

- **Domain:** `cloud.example.com`
- **Scheme:** `http`
- **Forward Hostname/IP:** `nextcloud`
- **Forward Port:** `80`
- **WebSocket Support:** ☑ Enabled
- **SSL:** Select your certificate, enable Force SSL

### Advanced Configuration

In the **Advanced** tab of the proxy host, add the following nginx directives for large file uploads and service discovery:

```nginx
# Allow large file uploads — must match or exceed PHP_UPLOAD_LIMIT (16G)
client_max_body_size 16G;
client_body_timeout 300s;
proxy_request_buffering off;

# CalDAV / CardDAV / WebDAV / WebFinger discovery
# https://docs.nextcloud.com/server/latest/admin_manual/issues/general_troubleshooting.html#service-discovery
location /.well-known/carddav {
    return 301 $scheme://$host/remote.php/dav;
}

location /.well-known/caldav {
    return 301 $scheme://$host/remote.php/dav;
}

location /.well-known/webfinger {
    return 301 $scheme://$host/index.php/.well-known/webfinger;
}

location /.well-known/nodeinfo {
    return 301 $scheme://$host/index.php/.well-known/nodeinfo;
}
```

> **Note:** `client_max_body_size` in NPM must match or exceed the `PHP_UPLOAD_LIMIT` set in the compose file (16G). Without this, NPM rejects large uploads before they reach Nextcloud. `proxy_request_buffering off` prevents NPM from buffering the entire upload in memory/disk before forwarding.
>
> **Service discovery:** The `.well-known` redirects enable CalDAV (calendar), CardDAV (contacts), and WebFinger discovery. Without these, Nextcloud's admin panel will show warnings, and calendar/contacts sync clients may fail to auto-discover the server.

## Port Forwarding

**No additional ports need to be forwarded.** Nextcloud runs entirely behind the reverse proxy — all traffic flows through HTTPS (port 443), which is already forwarded to Nginx Proxy Manager.

Unlike services with peer-to-peer protocols (e.g., Matrix/Coturn for voice/video, Syncthing for file sync), Nextcloud uses only standard HTTP/HTTPS for all operations including WebDAV file sync, CalDAV, and CardDAV.

## Performance Tuning

The compose file includes sensible defaults:

| Setting | Value | Purpose |
|---------|-------|---------|
| `PHP_MEMORY_LIMIT` | `1G` | Max memory per PHP process (Nextcloud recommends ≥512M) |
| `PHP_UPLOAD_LIMIT` | `16G` | Max file upload size (both `post_max_size` and `upload_max_filesize`) |
| `APACHE_BODY_LIMIT` | `0` | Unlimited Apache request body (defers limit to PHP) |
| `shm_size` (PostgreSQL) | `128mb` | Shared memory for PostgreSQL (prevents bus errors on large queries) |

To adjust these, modify the environment variables in `compose.nextcloud.yml` and recreate the container:
```bash
docker compose up -d nextcloud
```

## Maintenance

### Nextcloud OCC Command

The `occ` command-line tool manages your Nextcloud instance:

```bash
docker exec -it --user www-data nextcloud php occ <command>
```

Common commands:
```bash
# List installed apps
docker exec -it --user www-data nextcloud php occ app:list

# Run a manual file scan (e.g., after adding files directly to the data dir)
docker exec -it --user www-data nextcloud php occ files:scan --all

# Put Nextcloud into maintenance mode (for backups)
docker exec -it --user www-data nextcloud php occ maintenance:mode --on

# Check system status
docker exec -it --user www-data nextcloud php occ status

# View merged config (omits secrets by default)
docker exec -it --user www-data nextcloud php occ config:list system
```

### Backups

Back up both the database and file data:

```bash
# Database dump
docker exec nextcloud_postgres pg_dump -U nextcloud nextcloud > nextcloud-db-backup.sql

# File data is at ${RAID}/nextcloud — include in your regular RAID backup strategy
# Config/app data is at ${DATA}/nextcloud/html/config
```

> **Restore:** To restore, put Nextcloud in maintenance mode, import the SQL dump with `psql`, and ensure the data directory contents match. See the [Nextcloud backup/restore docs](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/backup.html) for the full procedure.

### Updates

To update Nextcloud, pull the latest image and recreate:
```bash
docker compose pull nextcloud
docker compose up -d nextcloud nextcloud_cron
```

> **Important:** Nextcloud only supports upgrading one major version at a time (e.g., 29 → 30 → 31, not 29 → 31). Check your current version with `docker exec --user www-data nextcloud php occ status` and consult the [Nextcloud upgrade documentation](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/upgrade.html) before jumping versions. Pin to a specific major version tag (e.g., `nextcloud:30-apache`) if you want controlled upgrades.

## Verification

After starting the stack, verify each component:

1. **Container health:**
   ```bash
   docker ps --filter "name=nextcloud" --format "table {{.Names}}\t{{.Status}}"
   ```
   All containers should show `Up` with `(healthy)` for postgres and redis.

2. **Access the web UI:**
   Navigate to `https://cloud.example.com` — you should see the Nextcloud login page (or the dashboard if auto-configured with admin credentials).

3. **Admin panel checks:**
   Go to **Administration Settings** → **Overview**. All warnings from step 7 should be resolved. If any remain, revisit [Initial Setup](#initial-setup) step 7.

4. **CalDAV/CardDAV discovery:**
   ```bash
   curl -sI https://cloud.example.com/.well-known/caldav
   ```
   Should return a `301` redirect to `/remote.php/dav`.

5. **Background jobs:**
   Go to **Administration Settings** → **Basic settings**. Confirm "Cron" is selected and "Last job ran" shows a recent timestamp.

6. **Desktop/mobile sync:** Install the [Nextcloud desktop client](https://nextcloud.com/install/#install-clients) or mobile app and verify file sync works.

## Troubleshooting

**502 Bad Gateway on first access:**
- Nextcloud is still initializing. Wait 1–3 minutes and try again. Check logs: `docker logs nextcloud`.

**"Access through untrusted domain" error:**
- Verify `NEXTCLOUD_HOSTNAME` in `.env` matches the domain you're accessing. If you need to fix it after first run, edit `${DATA}/nextcloud/html/config/config.php` and update the `trusted_domains` array.

**Homepage widget returns HTTP 400:**
- Other services (like Homepage) connect to Nextcloud via the internal Docker hostname `nextcloud`, which must be in the trusted domains list. The compose file includes it automatically via `NEXTCLOUD_TRUSTED_DOMAINS`, but this only takes effect on first install. To add it to an existing instance, first list current domains to find the next available index:
  ```bash
  docker exec -it --user www-data nextcloud php occ config:system:get trusted_domains
  ```
  Then add `nextcloud` at the next unused index (e.g., `2` if indices `0` and `1` are taken):
  ```bash
  docker exec -it --user www-data nextcloud php occ config:system:set trusted_domains 2 --value=nextcloud
  ```
  > **⚠️ Warning:** Each index can only hold one domain. Using an existing index **overwrites** that domain silently. Always check current values first to avoid accidentally removing your external hostname.

**".well-known" warnings in admin panel:**
- Ensure the Advanced nginx config (see [Advanced Configuration](#advanced-configuration)) is applied to your NPM proxy host. Test with `curl -sI https://cloud.example.com/.well-known/caldav`.

**Large file uploads fail:**
- Verify `client_max_body_size 16G;` is in the NPM Advanced config.
- Check that `PHP_UPLOAD_LIMIT` and `APACHE_BODY_LIMIT` match or exceed your needs.
- Intermediary network devices (some routers, cloudflare free tier) may also impose upload limits.

**Slow performance:**
- Confirm Redis is running: `docker exec nextcloud_redis redis-cli ping` should return `PONG`.
- Verify background jobs are running: **Administration Settings** → **Basic settings** → Background jobs should show "Cron" with a recent "Last job ran" timestamp.
- Verify APCu local cache is enabled (configured in step 7's `local.config.php`). If missing, add `'memcache.local' => '\OC\Memcache\APCu'` to `${DATA}/nextcloud/html/config/local.config.php`.

**Permission errors on data directory:**
- The Nextcloud container runs as `www-data` (uid 33). Ensure the data mount has appropriate permissions:
  ```bash
  chown -R 33:33 ${RAID}/nextcloud
  ```

**"Strict-Transport-Security" header warning:**
- Enable HSTS in the NPM proxy host: **SSL** tab → ☑ **HSTS Enabled**. Or add to the Advanced tab:
  ```nginx
  add_header Strict-Transport-Security "max-age=15552000; includeSubDomains" always;
  ```

## Resources

- [Nextcloud Documentation](https://docs.nextcloud.com/server/latest/admin_manual/)
- [Nextcloud Docker Image](https://github.com/nextcloud/docker)
- [Nextcloud Desktop/Mobile Clients](https://nextcloud.com/install/#install-clients)
- [Nextcloud Apps Store](https://apps.nextcloud.com/)
- [Nextcloud Reverse Proxy Guide](https://docs.nextcloud.com/server/latest/admin_manual/configuration_server/reverse_proxy_configuration.html)
- [Nextcloud Performance Tuning](https://docs.nextcloud.com/server/latest/admin_manual/installation/server_tuning.html)
- [Nextcloud Backup/Restore](https://docs.nextcloud.com/server/latest/admin_manual/maintenance/backup.html)
