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
| `/data/shared/torrents/music` | `/data/torrents/music` | Not mounted |
| `/data/shared/usenet/complete/music` | `/data/usenet/complete/music` | Not mounted |
| `/srv/docker/data/lidarr/config` | `/config` | Not mounted |

This follows the [TRaSH folder structure](https://trash-guides.info/File-and-Folder-Structure/How-to-set-up/Docker/)
already used for movies and TV: the `music` folders under `media`, `torrents`,
and `usenet/{incomplete,complete}` already exist on the server. qBittorrent
mounts `${RAID}/shared/torrents:/data/torrents` and SABnzbd mounts
`${RAID}/shared/usenet:/data/usenet`, so every app reports the same paths.

Lidarr mounts `${RAID}/shared:/data`, like Sonarr/Radarr. Its library,
purchase-import staging, and download paths share one mount and one XFS
filesystem, so torrent imports are hardlinks and Usenet/purchase imports are
instant moves. Never mount `torrents`, `usenet`, and `media/music` into Lidarr
as separate volumes; Docker treats each bind mount as a separate filesystem
and imports silently degrade to full copies. Plex already mounts
`${RAID}/shared/media:/data/media`; do not add a second music mount or change
existing movie/TV libraries. Lidarr is the music file manager; Plex only needs
to read this directory (its existing broad media mount is unchanged).

Keep untouched purchase downloads and receipts backed up separately before
importing. RAID is not a backup. Lidarr's database/config also needs backup.

## First-time setup after merging

These are manual production steps, not actions performed by the PR. Do not
deploy this feature branch to the server just to review it.

### 1. Create directories and start Lidarr

The `music` folders under `media`, `torrents`, and `usenet` already exist.
Create the purchase staging folder and Lidarr config as the server's media
owner (`danteb`, group `docker`, matching the existing folders):

```bash
install -d -m 2775 /data/shared/imports/music /srv/docker/data/lidarr/config
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
4. Leave audio-tag rewriting disabled (it breaks seeding hardlinks; see step 4)
   and automatic track renaming disabled initially,
   particularly for Japanese editions and compilations. Review album/release
   matches before importing. Include soundtrack/compilation/EP release types
   in a metadata profile when the default profile excludes the desired release.

A FLAC-only profile filters acquisitions; it does not convert existing MP3/AAC
files into lossless audio or prove a download's provenance. Allow both FLAC
qualities so purchased 24-bit albums are not rejected. Do not upsample or
re-encode lossy music to FLAC. CD-quality 16-bit/44.1 kHz is already lossless;
a good master matters more than a hi-res badge. Recyclarr's existing
Sonarr/Radarr configuration does not configure Lidarr.

### 4. Download clients, Prowlarr, and hardlinks

Purchases can be imported without indexers or download clients. For automated
downloads, mirror the Radarr/Sonarr setup: both use a category named after the
media type (`movies`, `tv`, `anime-tv`, ...), not after the app.

**qBittorrent** (Web UI > right-click categories > Add category):

| Category | Save path | Resolves to |
|----------|-----------|-------------|
| `music` | `music` | `/data/torrents/music` |

Automatic Torrent Management is already the default, so the relative save path
is joined to the `/data/torrents` default save path.

**SABnzbd** (Config > Categories):

| Category | Priority | Processing | Script | Folder/Path |
|----------|----------|------------|--------|-------------|
| `music` | Default | Default | Default | `music` |

Relative folders resolve under the completed folder,
`/data/usenet/complete/music`. Leave the existing `*` default category and
video categories unchanged.

**Lidarr**:

| Where | Configuration |
|-------|---------------|
| Settings > Download Clients > qBittorrent | Name `qBittorrent`, host `qbittorrent`, port `8080`, existing Web UI credentials, category `music`, leave *Post-Import Category* empty |
| Settings > Download Clients > SABnzbd | Name `SABnzbd`, host `sabnzbd`, port `8080`, existing API key, category `music` |
| Settings > Download Clients > Completed Download Handling | Enabled (default) |
| Settings > Download Clients > Remote Path Mappings | None; all apps already see `/data/...` |
| Settings > Media Management > Importing | *Use Hardlinks instead of Copy* enabled (default) |
| Settings > Metadata > Tag Audio Files with Metadata | `Never` (see below) |
| Prowlarr > Settings > Apps > Lidarr | Prowlarr server `http://prowlarr:9696`, Lidarr server `http://lidarr:8686`, Lidarr API key, default Audio sync categories; test, save, then *Sync App Indexers* |

Use `qbittorrent`, the VPN namespace's network alias, not `qbittorrent-app`.
Never point a download category at `/data/media/music` or the import staging
folder.

**Do not let Lidarr write tags to hardlinked files.** A hardlink is the same
data as the seeding torrent, so retagging the library copy also changes the
torrent's payload; the torrent then fails its hash check and stops seeding.
Keep *Tag Audio Files with Metadata* at `Never` and fix tags in MusicBrainz Picard on a copy
before importing instead. Usenet and purchased imports are moves, not
hardlinks, but one global setting covers all of them.

Verify a hardlink after the first torrent import (link count `2` and the same
inode for both paths):

```bash
stat -c '%h %i %n' "/data/shared/torrents/music/<release>/<track>.flac" \
  "/data/shared/media/music/<Artist>/<Album>/<track>.flac"
```

**qbit-manage**: add `music` to the private
`${DATA}/qbit-manage/config/config.yml` `cat:` mapping
(`music: /data/torrents/music`) and to its `nohardlinks:` list, alongside the
video categories. See [qBit Manage inactivity cleanup](QBIT-MANAGE-INACTIVITY.md).

**Quality guidance**: TRaSH Guides has no Lidarr guide and Recyclarr does not
sync Lidarr; TRaSH points to
[Davo's Community Lidarr Guide](https://wiki.servarr.com/lidarr/community-guide).
The `FLAC Only` profile above is maintained by hand.

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
- For optional automated downloads, confirm a `music`-category torrent lands
  in `/data/torrents/music`, imports into the music root as a hardlink (link
  count 2), keeps seeding, and the FLAC-only profile rejects lossy releases.

## References

- [Lidarr quick start](https://wiki.servarr.com/lidarr/quick-start-guide)
- [Importing an existing library](https://wiki.servarr.com/lidarr/importing-existing-library)
- [Hotio Lidarr image](https://hotio.dev/containers/lidarr/)
- [Plexamp features and downloads](https://www.plex.tv/plexamp/)
- [Homepage Lidarr widget](https://gethomepage.dev/widgets/services/lidarr/)
