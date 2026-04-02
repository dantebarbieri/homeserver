# Homepage Widget API Keys

Step-by-step instructions for obtaining every `HOMEPAGE_VAR_*` token in
`docker/sample.env`. Each key feeds into a Homepage
[service widget](https://gethomepage.dev/widgets/services/) so the dashboard can
display live stats.

> **Tip:** After obtaining a key, paste it into your `.env` file next to the
> matching variable and restart Homepage (`docker compose up -d homepage`).

---

## Plex — `HOMEPAGE_VAR_PLEX_TOKEN`

The Plex token is tied to your account, not a settings page.

1. Sign in to [Plex Web](https://app.plex.tv) and open any media item.
2. Click **⋮ → Get Info → View XML**.
3. In the URL bar, copy the `X-Plex-Token=…` query parameter value.

Alternatively, inspect any Plex web request's headers in your browser DevTools
and look for `X-Plex-Token`.

📖 [Plex support article](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

---

## Jellyfin — `HOMEPAGE_VAR_JELLYFIN_KEY`

1. Open Jellyfin (e.g. `https://jellyfin.danteb.com`).
2. Go to **Administration → Dashboard → API Keys** (under *Advanced*).
3. Click **+** to create a new key, name it `homepage`.
4. Copy the generated key.

---

## Seerr — `HOMEPAGE_VAR_SEERR_KEY`

1. Open Seerr (e.g. `https://seerr.danteb.com`).
2. Go to **Settings**.
3. The **API Key** is displayed at the top of the General Settings page.
4. Copy the key.

---

## Immich — `HOMEPAGE_VAR_IMMICH_KEY`

1. Open Immich (e.g. `https://immich.danteb.com`).
2. Click your user avatar → **Account Settings**.
3. Scroll to **API Keys** and click **New API Key**.
4. Name it `homepage` and click **Create**.
5. Copy the key (it is only shown once).

---

## Komga — `HOMEPAGE_VAR_KOMGA_USER` / `HOMEPAGE_VAR_KOMGA_PASS`

Komga uses basic authentication rather than an API key.

1. Set `HOMEPAGE_VAR_KOMGA_USER` to your Komga username.
2. Set `HOMEPAGE_VAR_KOMGA_PASS` to your Komga password.

If you prefer a dedicated account, create a new user in
**Settings → Users** with read-only access.

---

## Radarr — `HOMEPAGE_VAR_RADARR_KEY`

1. Open Radarr (e.g. `https://radarr.danteb.com`).
2. Go to **Settings → General**.
3. Under *Security*, find the **API Key** field.
4. Copy the key.

---

## Sonarr — `HOMEPAGE_VAR_SONARR_KEY`

1. Open Sonarr (e.g. `https://sonarr.danteb.com`).
2. Go to **Settings → General**.
3. Under *Security*, find the **API Key** field.
4. Copy the key.

---

## Bazarr — `HOMEPAGE_VAR_BAZARR_KEY`

1. Open Bazarr (e.g. `https://bazarr.danteb.com`).
2. Go to **Settings → General**.
3. The **API Key** is shown under the *Security* section.
4. Copy the key.

---

## Prowlarr — `HOMEPAGE_VAR_PROWLARR_KEY`

1. Open Prowlarr (e.g. `https://prowlarr.danteb.com`).
2. Go to **Settings → General**.
3. Under *Security*, find the **API Key** field.
4. Copy the key.

---

## SABnzbd — `HOMEPAGE_VAR_SABNZBD_KEY`

1. Open SABnzbd (e.g. `https://sabnzbd.danteb.com`).
2. Go to **Config → General** (the gear icon).
3. Under *SABnzbd Web Server*, find the **API Key** field.
4. Copy the key.

---

## Nginx Proxy Manager — `HOMEPAGE_VAR_NPM_USER` / `HOMEPAGE_VAR_NPM_PASS`

NPM authenticates via username/password, not a token.

1. Set `HOMEPAGE_VAR_NPM_USER` to your NPM admin email.
2. Set `HOMEPAGE_VAR_NPM_PASS` to the corresponding password.

If you prefer a dedicated account, create a new user in NPM's
**Users** tab with a limited role.

---

## Tdarr — `HOMEPAGE_VAR_TDARR_KEY`

Tdarr requires an API key when authentication is enabled.

1. Open Tdarr (e.g. `https://tdarr.danteb.com`).
2. Go to **Settings** (gear icon).
3. Under *Authentication*, find or generate the **API Key**.
4. Copy the key.

> **Note:** This is the same value as `TDARR_API_KEY` in `docker/sample.env`.
> You can reuse it, but Homepage needs its own `HOMEPAGE_VAR_TDARR_KEY` variable
> so the key is passed through to the container's environment.

---

## qBittorrent — `HOMEPAGE_VAR_QBIT_USER` / `HOMEPAGE_VAR_QBIT_PASS`

qBittorrent authenticates via username/password.

1. Set `HOMEPAGE_VAR_QBIT_USER` to your qBittorrent Web UI username
   (default: `admin`).
2. Set `HOMEPAGE_VAR_QBIT_PASS` to the corresponding password.

> **Tip:** If Homepage has been IP-banned from too many failed login attempts,
> restart the qBittorrent container to clear the ban:
> `docker compose restart qbittorrent-app`

---

## Nextcloud — `HOMEPAGE_VAR_NEXTCLOUD_USER` / `HOMEPAGE_VAR_NEXTCLOUD_PASS`

Nextcloud uses admin credentials to access the serverinfo API.

**Recommended: Use an app password** (avoids special character escaping issues in `.env`):

1. Log in to Nextcloud as admin.
2. Go to **Settings** → **Security** → **Devices & sessions**.
3. Enter a name (e.g., `homepage`) and click **Create new app password**.
4. Set `HOMEPAGE_VAR_NEXTCLOUD_USER` to your admin username.
5. Set `HOMEPAGE_VAR_NEXTCLOUD_PASS` to the generated app password.

Alternatively, set `HOMEPAGE_VAR_NEXTCLOUD_PASS` to the admin account password directly. If the password contains special characters (`$`, `#`, `!`, `\`, backticks), wrap the value in single quotes in `.env` to prevent Docker Compose from interpreting them.

> **Note:** The serverinfo API (`/ocs/v2.php/apps/serverinfo/api/v1/info`)
> requires admin privileges. A non-admin user will not work.

---

## AdGuard Home — `HOMEPAGE_VAR_ADGUARD_USERNAME` / `HOMEPAGE_VAR_ADGUARD_PASSWORD`

AdGuard Home authenticates via the admin credentials created during initial setup.

1. Set `HOMEPAGE_VAR_ADGUARD_USERNAME` to the admin username chosen during setup.
2. Set `HOMEPAGE_VAR_ADGUARD_PASSWORD` to the corresponding password.

📖 [AdGuard Home Wiki](https://github.com/AdguardTeam/AdGuardHome/wiki)

---

## Uptime Kuma — `HOMEPAGE_VAR_KUMA_SLUG`

Uptime Kuma's Homepage widget reads data from a **status page**, not an API key.

1. Open Uptime Kuma (e.g. `https://uptime.danteb.com`).
2. Go to **Status Pages** (sidebar).
3. Create a status page (e.g., "homeserver") and add your monitors.
4. The slug is the last segment of the status page URL:
   `https://uptime.danteb.com/status/<slug>`.
5. Set `HOMEPAGE_VAR_KUMA_SLUG` to that slug value (e.g., `homeserver`).

---

## Suwayomi — `HOMEPAGE_VAR_SUWAYOMI_USER` / `HOMEPAGE_VAR_SUWAYOMI_PASS`

Use the username and password configured for Suwayomi's basic authentication.
These are the credentials you use to log into the Suwayomi web UI at
`https://suwayomi.danteb.com`.

---

## Quick Reference

| Variable | Service | Type |
|---|---|---|
| `HOMEPAGE_VAR_PLEX_TOKEN` | Plex | Account token |
| `HOMEPAGE_VAR_JELLYFIN_KEY` | Jellyfin | API key |
| `HOMEPAGE_VAR_SEERR_KEY` | Seerr | API key |
| `HOMEPAGE_VAR_IMMICH_KEY` | Immich | API key |
| `HOMEPAGE_VAR_KOMGA_USER` | Komga | Username |
| `HOMEPAGE_VAR_KOMGA_PASS` | Komga | Password |
| `HOMEPAGE_VAR_RADARR_KEY` | Radarr | API key |
| `HOMEPAGE_VAR_SONARR_KEY` | Sonarr | API key |
| `HOMEPAGE_VAR_BAZARR_KEY` | Bazarr | API key |
| `HOMEPAGE_VAR_PROWLARR_KEY` | Prowlarr | API key |
| `HOMEPAGE_VAR_SABNZBD_KEY` | SABnzbd | API key |
| `HOMEPAGE_VAR_NPM_USER` | Nginx Proxy Manager | Email |
| `HOMEPAGE_VAR_NPM_PASS` | Nginx Proxy Manager | Password |
| `HOMEPAGE_VAR_TDARR_KEY` | Tdarr | API key |
| `HOMEPAGE_VAR_QBIT_USER` | qBittorrent | Username |
| `HOMEPAGE_VAR_QBIT_PASS` | qBittorrent | Password |
| `HOMEPAGE_VAR_NEXTCLOUD_USER` | Nextcloud | Username (admin) |
| `HOMEPAGE_VAR_NEXTCLOUD_PASS` | Nextcloud | Password / app password |
| `HOMEPAGE_VAR_ADGUARD_USERNAME` | AdGuard Home | Username |
| `HOMEPAGE_VAR_ADGUARD_PASSWORD` | AdGuard Home | Password |
| `HOMEPAGE_VAR_SUWAYOMI_USER` | Suwayomi | Username |
| `HOMEPAGE_VAR_SUWAYOMI_PASS` | Suwayomi | Password |
| `HOMEPAGE_VAR_KUMA_SLUG` | Uptime Kuma | Status page slug |
