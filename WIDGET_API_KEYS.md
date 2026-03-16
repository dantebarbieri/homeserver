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

## Overseerr — `HOMEPAGE_VAR_OVERSEERR_KEY`

1. Open Overseerr (e.g. `https://overseerr.danteb.com`).
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

## Quick Reference

| Variable | Service | Type |
|---|---|---|
| `HOMEPAGE_VAR_PLEX_TOKEN` | Plex | Account token |
| `HOMEPAGE_VAR_JELLYFIN_KEY` | Jellyfin | API key |
| `HOMEPAGE_VAR_OVERSEERR_KEY` | Overseerr | API key |
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
