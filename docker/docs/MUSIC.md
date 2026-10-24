# Music - Lidarr + Plexamp

Lidarr manages artists, albums, and imports. The existing Plex server serves
the music; **Plexamp** is the dedicated player on iPhone, Windows, and macOS.
No additional playback container or duplicate library is needed.

| Component | Address | Role |
|-----------|---------|------|
| Lidarr | `https://lidarr.danteb.com` / internally `http://lidarr:8686` | Library management; optional Prowlarr/download-client integration |
| Plex | Existing Plex server | Music library, accounts, and streaming |
| Plexamp | Install on each listening device | Music-focused playback, gapless, CarPlay, and FLAC support |

[Plexamp core playback is free](https://www.plex.tv/plexamp/). Plex Pass unlocks
offline downloads, sonic discovery, and other premium features. Plexamp uses
Plex, not Navidrome. An independent alternative is Navidrome with Amperfy on
iPhone and Feishin on Windows/macOS, but that is not deployed by this setup.

## Library and ownership

| Host path (default `.env`) | Lidarr path | Plex path |
|---------------------------|-------------|-----------|
| `/data/shared/media/music` | `/data/media/music` | `/data/media/music` |
| `/data/shared/imports/music` | `/data/imports/music` | Not mounted |
| `/data/shared/torrents` | `/data/torrents` | Not mounted |
| `/data/shared/usenet` | `/data/usenet` | Not mounted |
| `/srv/docker/data/lidarr/config` | `/config` | Not mounted |

Lidarr mounts `${RAID}/shared:/data`, like Sonarr/Radarr. Its library,
purchase-import staging, and download paths share one mount so imports can
use atomic moves/hardlinks where appropriate. Plex already mounts
`${RAID}/shared/media:/data/media`; do not add a second music mount or change
existing movie/TV libraries. Lidarr is the music file manager; Plex only needs
to read this directory (its existing broad media mount is unchanged).

Keep untouched purchase downloads and receipts backed up separately before
importing. RAID is not a backup. Lidarr's database/config also needs backup.

## First-time setup after merging

These are manual production steps, not actions performed by the PR. Do not
deploy this feature branch to the server just to review it.

### 1. Create directories and start Lidarr

Use the actual UID/GID and paths from the server's `docker/.env` if different:

```bash
sudo install -d -o 1000 -g 1000 -m 2775 \
  /data/shared/media/music \
  /data/shared/imports/music \
  /srv/docker/data/lidarr/config
z /srv/homeserver/docker
docker compose pull lidarr
docker compose up -d lidarr
```

Always use the main Compose entry point; starting a category file separately
can create the wrong networks. Lidarr inherits PUID/PGID/TZ, restart policy,
and bounded logging from `hotio-service`. Its umask is `002`.

### 2. Reverse proxy and authentication

Create an NPM proxy host for `lidarr.danteb.com` forwarding to
`http://lidarr:8686`, with TLS, WebSockets, and Block Common Exploits enabled.
Keep Lidarr's own authentication enabled and require login for all addresses,
including local addresses. Complete its initial account setup through a
private connection before exposing the proxy publicly (for example, use an
SSH tunnel to the container IP on port 8686).

Lidarr has built-in authentication; do not add a second Authelia login here.
Prowlarr and Homepage use the internal address and Lidarr API key. No host
ports are published, so no NixOS firewall or router changes are needed.
Wildcard DNS already covers the new hostname.

### 3. Configure a FLAC-only library

In Lidarr:

1. Add `/data/media/music` as the root folder under **Settings > Media
   Management**. Never use a downloads or import-staging directory as the root.
2. Create a quality profile named `FLAC Only`, enable **only FLAC and FLAC
   24bit**, and disable upgrades initially. Expand/edit the Lossless group so
   ALAC, APE, WavPack, and other formats are not inadvertently allowed with it.
   Assign this profile to the root's defaults and to every artist you add;
   existing artists retain their own assigned profiles.
3. Start with artists/albums **unmonitored** and automatic searches off while
   importing purchases. Enable monitoring deliberately for albums you want
   Lidarr to acquire through sources you are authorized to use.
4. Leave audio-tag rewriting and automatic track renaming disabled initially,
   particularly for Japanese editions and compilations. Review album/release
   matches before importing. Include soundtrack/compilation/EP release types
   in a metadata profile when the default profile excludes the desired release.

A FLAC-only profile filters acquisitions; it does not convert existing MP3/AAC
files into lossless audio or prove a download's provenance. Allow both FLAC
qualities so purchased 24-bit albums are not rejected. Do not upsample or
re-encode lossy music to FLAC. CD-quality 16-bit/44.1 kHz is already lossless;
a good master matters more than a hi-res badge. Recyclarr's existing
Sonarr/Radarr configuration does not configure Lidarr.

### 4. Optional existing Starr integrations

Purchases can be imported without indexers or download clients. If using your
existing infrastructure, configure these through the application UIs; no keys
or production databases are committed here:

| Where | Configuration |
|-------|---------------|
| Prowlarr > Settings > Apps > Lidarr | Prowlarr server `http://prowlarr:9696`, Lidarr server `http://lidarr:8686`, Lidarr API key; select suitable music categories and test before syncing |
| Lidarr > Settings > Download Clients > qBittorrent | Host `qbittorrent`, port `8080`, existing credentials, dedicated category `lidarr` |
| Lidarr > Settings > Download Clients > SABnzbd | Host `sabnzbd`, port `8080`, existing API key, dedicated category `lidarr` |

Use `qbittorrent`, the VPN namespace's network alias, not `qbittorrent-app`.
Use download destinations under `/data/torrents` or `/data/usenet` respectively,
outside `/data/media/music`. The paths reported by clients already match the
paths visible to Lidarr; no remote path mapping should be needed. Test each
connection and enable Completed Download Handling. Leave existing video
categories and VPN configuration unchanged.

If enabling hardlinks for seeding, remember that editing tags in a hardlinked
library file also changes the seeding file. Keep metadata rewriting disabled,
or use separate copies when files must be modified.

### 5. Purchased FLACs

Buy/download actual files, rather than a streaming app's offline cache:

| Store | Good use |
|-------|----------|
| [Qobuz download store](https://www.qobuz.com/us-en/shop) | Broad label catalogue; buy CD-quality or hi-res FLAC when offered, independently of a streaming subscription |
| [Bandcamp](https://bandcamp.com/) | Independent artists/labels; choose FLAC on the purchase download page |
| [mora](https://mora.jp/) | Japanese releases; explicitly choose the FLAC/hi-res product, not an AAC-only listing |
| [OTOTOY](https://ototoy.jp/) | Japanese/independent releases; check the formats offered for that release |

Catalogues, formats, payment methods, and territorial purchase eligibility vary.
Use stores where you are eligible to purchase. A lossless streaming subscription
does not grant a portable collection of purchased FLACs. Lidarr does not buy
albums or download your storefront purchases; this setup does not add
stream-ripping tools or store credentials.

Download with the store's official website/app on Windows or Mac. Keep the
original archive, extract a working copy, and transfer complete albums into
`/data/shared/imports/music/<Artist>/<Album>/` on the server, preserving the
UID/GID's read/write permissions. Include embedded artist, album artist, album,
track/disc numbers, and release metadata; MusicBrainz Picard is useful for
reviewing tags on a copy, but confirm the exact Japanese edition before saving.

In Lidarr, add the artist with `FLAC Only`, no monitoring, and no search. Use
**Wanted > Manual Import** on `/data/imports/music`; review artist, album,
release, disc/track mapping, and detected quality, then import into the music
root. Prefer copy mode if you want to retain staging files. Confirm the
library copy and playback before cleaning up staging.

Lidarr uses MusicBrainz and can struggle with missing releases, unusual
Japanese editions, singles, and compilations. Do not force a wrong match or
delete an unmatched purchase. You can instead place a correctly tagged album
directly under `/data/shared/media/music/<Album Artist>/<Album>/` and let Plex
play it without Lidarr management. Leave it unmonitored/unmanaged until a
correct metadata match exists. Plex playback does not depend on Lidarr.

### 6. Plex and Plexamp

In Plex Web, create a **Music** library named `Music` with folder
`/data/media/music`. Enable automatic library scanning, and run an initial
scan. Use Plex Music metadata; prefer local metadata if preserving your
carefully tagged editions is more important than Plex's matches. With Plex
Pass, enable sonic analysis if desired; its initial analysis can take time.

Install [Plexamp](https://www.plex.tv/plexamp/) on iPhone, Windows, and macOS,
sign into the existing Plex account, and choose this server's Music library.
Grant the Music library to any other Plex users who should have access.
Do not put Authelia in front of Plex's client/API endpoints.

For lossless streaming, choose **Original/Maximum** music quality for Wi-Fi
and cellular as desired; this uses more mobile data. Check Plex's playback
dashboard for **Direct Play** and FLAC during a session. If using offline
downloads (Plex Pass), also choose original quality there. Lower mobile
bitrates are fine when intentional and do not alter the stored FLACs.

FLAC delivery does not guarantee bit-perfect output at the headphones.
Bluetooth is generally lossy; use a compatible wired DAC/headphones for a
lossless output path. OS mixing, effects, and sample-rate settings can also
affect output. Do not assume hi-res playback from the filename alone.

### 7. Homepage

Copy Lidarr's **Settings > General > Security > API Key** into
`HOMEPAGE_VAR_LIDARR_KEY` in the server's `docker/.env`, then:

```bash
z /srv/homeserver/docker
docker compose up -d homepage
```

The new Media Management tile uses `http://lidarr:8686` internally for its
widget and `https://lidarr.danteb.com` for the browser/monitor.

## Acceptance checks

- Lidarr requires login through NPM; its Homepage widget and optional Prowlarr
  connection succeed with the API key.
- Import one purchased FLAC album and verify its edition, tags, ownership,
  and destination under `/data/shared/media/music`.
- Plex indexes it without disturbing existing movie/TV libraries.
- Play it in Plexamp on iPhone and both desktops; check Direct Play/FLAC.
- If using Plex Pass downloads, verify playback in airplane mode.
- For optional automated downloads, confirm a dedicated category imports into
  the music root and the FLAC-only profile rejects lossy releases.

## References

- [Lidarr quick start](https://wiki.servarr.com/lidarr/quick-start-guide)
- [Importing an existing library](https://wiki.servarr.com/lidarr/importing-existing-library)
- [Hotio Lidarr image](https://hotio.dev/containers/lidarr/)
- [Plexamp features and downloads](https://www.plex.tv/plexamp/)
- [Homepage Lidarr widget](https://gethomepage.dev/widgets/services/lidarr/)
