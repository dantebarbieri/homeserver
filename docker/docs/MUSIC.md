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
video categories. Do the same for `music-manual: /data/torrents/music-manual`,
where `lidarr-maint` parks hand-imported torrents. See [qBit Manage inactivity cleanup](QBIT-MANAGE-INACTIVITY.md).

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

## Current production configuration

The setup steps above describe the initial rollout; production has since moved
on. These are configured in the apps (not in this repo):

| Setting | Value |
|---------|-------|
| Quality profile | `Lossless Preferred`: Lossless group + `MP3 320/V0` fallback, cutoff Lossless, upgrades on. Used by all artists and the Spotify import list (`FLAC Only` is unused) |
| Metadata profiles | `Standard` (Album, EP, Single), `Soundtracks` (Soundtrack/Compilation, for Studio Ghibli) |
| Renaming | On: `{Album Title} ({Release Year})/{track:00} - {Track Title}`, multi-disc `{medium:0}-{track:00}`, artist folder `{Artist Name}`. Renames keep hardlinks (same inode) |
| Import list | Spotify playlists: monitor specific album, no new albums |
| Connect | Plex Media Server (`plex:32400`), *Update Library* on import. Plex's own change detection misses Lidarr imports |
| Indexers | NZBgeek, The Pirate Bay, 1337x, kickasstorrents, Internet Archive. Torrent minimum seeders `2` (music is thinly seeded) |
| Prowlarr app sync | Lidarr app is `Add and Remove Only` so the per-indexer seeder override survives syncs; add new indexers in Lidarr by hand or let Prowlarr add them |

Prowlarr runs with `DOTNET_SYSTEM_NET_DISABLEIPV6=1`: FlareSolverr solves
Cloudflare over IPv4 and `cf_clearance` is bound to that IP, so Prowlarr must
replay it over IPv4 too (over IPv6 it gets 403 "blocked by CloudFlare").

Lidarr's MusicBrainz titles for Japanese releases (e.g. Ghibli soundtracks)
are in Japanese while indexers use English, so automatic search rarely matches.
Grab those manually and import with **Wanted > Manual Import**, choosing the
release whose track count matches the files. `lidarr-maint` (below) does this
automatically when the files are already in Lidarr's queue.

Add hand-grabbed torrents to qBittorrent's `music-manual` category, not
`music`, and import them with `copy` (hardlink). Lidarr tracks everything in
`music`. If a torrent wasn't grabbed by Lidarr, it reappears in the queue as
"Import failed" on every poll, even after a successful manual import. A queue
*Remove* without removing it from the client only hides it until the next
poll. If one is already in `music`, change its category to `music-manual`.
qBittorrent's automatic torrent management moves it on the same filesystem,
so the hardlinks survive.

## Queue maintenance (`lidarr-maint`)

`lidarr-maint` (`compose.starr.yml`, built from the shared `dockerfiles/arr-maint/` image (common engine in `arr_maint.py`, Lidarr rules in `lidarr.py`))
checks Lidarr's queue every 30 minutes. It only acts on items that have been
stuck for at least 20 minutes (`GRACE_MINUTES`), so Lidarr gets the first try:

| Stuck pattern | Fix |
|---------------|-----|
| Import failed because Lidarr expected another edition (common for soundtracks) | If the file count matches another release and the titles match, manual-import into it (copy for torrents to keep hardlinks, move for usenet). Never switches the edition of an album that already has files, since that unlinks them |
| Single/EP grabbed for an album (<=4 files for an 8+ track album) | Blocklist + re-search |
| Failed download | Blocklist + re-search |
| Dead torrent: no connected seeds for 24 h (`STALL_HOURS`) and either below 5%, including stuck on "downloading metadata", or partly done with availability below 1 and no activity for 24 h (Lidarr's qBittorrent category, `music`) | Blocklist + re-search |
| "Not grabbed by Lidarr" torrents | Move to `music-manual` (below), download kept |
| "Not grabbed by Lidarr" usenet entries | Remove from the queue (download kept) |
| Completed torrent with no artist match ("Artist name mismatch"), whose files were already imported by hand (hardlink count > 1) | Move the torrent to the `music-manual` qBit category (`/data/torrents/music-manual`), which Lidarr doesn't track, so it keeps seeding. Lidarr v3's queue *Remove* returns HTTP 500 for these unknown-artist items. Without hardlinked files, it notifies instead |
| Missing albums | `MissingAlbumSearch` at most every 6 h |

Anything else, such as partial edition matches, archives, or an album grabbed
under the wrong album, is posted once to ntfy (`homeserver-alerts`) as
"Lidarr: needs attention". A failing run alerts at high priority, and repeats of
the same error at most every 6 hours. The container reads Lidarr's API key from
its `config.xml` (read-only), so key rotations need no change. It uses the
qBittorrent's `QUSER`/`QPASS` credentials and keeps its state in
`${DATA}/lidarr-maint`. It mounts `/data` read-only because Lidarr itself
performs the imports.

```bash
docker logs -f lidarr-maint                                   # what it did
docker compose run --rm -e DRY=1 -e ONCE=1 lidarr-maint       # preview one run
```

## Soulseek (slskd + Soularr)

Soulseek has far more lossless music, especially niche and Japanese releases,
than public trackers. Two containers add it:

| Container | Address | Role |
|-----------|---------|------|
| `slskd` | `https://slskd.danteb.com` / `http://slskd:5030` | Soulseek client; built-in login (no Authelia) |
| `soularr` | `https://soularr.danteb.com` / `http://soularr:8265` | Every 5 min, searches slskd for Lidarr's missing albums, downloads the best match, and tells Lidarr to import it. Web UI has no auth, so NPM uses Authelia |

slskd runs inside its own VPN stack in `compose.downloads.yml`:
`slskd-netns` (pause container, `slskd` alias on `proxy`) → `gluetun-slskd`
(a **second** ProtonVPN WireGuard tunnel) → `slskd` + `slskd-port-sync`.
ProtonVPN forwards one port per tunnel and qBittorrent owns the first one, so
slskd gets its own tunnel; `slskd-port-sync` pushes the forwarded port into
slskd's listen port (re-applied after restarts) and alerts via ntfy if it
disappears. `slskd-netns-watcher` recreates the stack if the pause container
is replaced. No host ports, firewall, or router changes.

| Host path | slskd | Lidarr | Soularr |
|-----------|-------|--------|---------|
| `/data/shared/soulseek/downloads` | `/data/soulseek/downloads` | `/data/soulseek/downloads` | `/downloads` |
| `/data/shared/soulseek/incomplete` | `/data/soulseek/incomplete` | — | — |
| `/data/shared/media/music` | `/music` (read-only share) | `/data/media/music` | — |
| `/srv/docker/data/slskd` | `/app` | — | — |
| `/srv/docker/data/soularr` | — | — | `/data` (`config.ini`) |

Downloads sit on the same filesystem as the library, so Lidarr's import is an
instant move. Nothing seeds from the download folder (slskd shares the library
itself), so hardlinks aren't needed here.

### Setup

1. In ProtonVPN, create a second WireGuard config with **NAT-PMP (port
   forwarding)** on; put its key and address in `.env` as
   `SLSKD_WG_PRIVATE_KEY` / `SLSKD_WG_ADDRESS`.
2. Fill the other `SLSKD_*` variables in `.env` (see `sample.env`). The
   Soulseek account is registered on first login if the username is free.
3. Create directories and start the stack:

   ```bash
   install -d -m 2775 -o danteb -g docker /data/shared/soulseek/{downloads,incomplete} \
     /srv/docker/data/slskd /srv/docker/data/soularr
   z /srv/homeserver/docker
   docker compose up -d --build slskd-netns gluetun-slskd slskd slskd-port-sync slskd-netns-watcher
   ```

4. Write `/srv/docker/data/soularr/config.ini` from the
   [Soularr example](https://github.com/mrusse/soularr#configure-your-config-file)
   with: Lidarr `host_url = http://lidarr:8686`, `download_dir =
   /data/soulseek/downloads`; Slskd `host_url = http://slskd:5030`,
   `download_dir = /downloads`, `api_key` = `SLSKD_API_KEY`;
   `allowed_filetypes = flac 24/192,flac 24/96,flac 24/48,flac 16/44.1,flac,alac,mp3 320,mp3`;
   `skip_region_check = True`; `search_source = missing`;
   `ignore_failed_users = True`; `search_retry_wait_hours = 24`;
   `album_prepend_artist = True`; `search_timeout = 15000`;
   `use_extension_whitelist = True` with `extensions_whitelist = lrc,cue,log,jpg,png`.
   Keep it mode 600. Without `album_prepend_artist`, Soularr searches the bare
   album title, so singles with generic names ("Soldier", "Easy") return
   hundreds of unrelated results and never match. The default 5 s timeout
   also cuts off most peer responses. After changing search settings, reset
   `search_attempts.json` to `{}` so every missing album is retried at once.
5. Add `soularr.danteb.com` to the `group:dev` two-factor rule in Authelia's
   `access_control` (the default policy is `deny`) and restart Authelia.
6. NPM proxy hosts (TLS, WebSockets): `slskd.danteb.com` → `http://slskd:5030`
   (no Authelia) and `soularr.danteb.com` → `http://soularr:8265` with the
   Authelia advanced config used by `dashdot.danteb.com`
   (`authelia-location.conf` + a `location /` including
   `authelia-authrequest.conf`). Add Authelia **before** the first request:
   Soularr's unauthenticated `/api/config` returns `config.ini` including both
   API keys. Confirm `https://soularr.danteb.com/` answers 302 to Authelia.
   Then `docker compose up -d soularr homepage`.

`SLSKD_REMOTE_CONFIGURATION` must stay `true`: `slskd-port-sync` sets the
listen port with `PATCH /api/v0/options`, which slskd rejects (403) otherwise.

Check `docker logs slskd-port-sync` shows the forwarded port applied and the
slskd UI shows connected. Soularr logs each search; Lidarr's history shows the
imports.

## Requests (Aurral)

[Aurral](https://docs.aurral.org/) is the Seerr equivalent for music:
search MusicBrainz, then **Download album** / **Monitor** sends the request
to Lidarr (which still owns quality, downloading, and importing). Aurral reads
Lidarr's files at the same paths, so it mounts `${RAID}/shared` at `/data`
like Lidarr. It has its own users, so NPM has no Authelia in front of it
(same as Seerr).

1. `docker compose up -d aurral homepage`
2. NPM proxy host `aurral.danteb.com` → `http://aurral:3001` (TLS,
   WebSockets, Block Common Exploits). Until the admin account exists, anyone
   reaching it can claim admin, so keep the Authelia advanced config (and an
   Authelia rule) on the host during onboarding, then remove both.
3. Open it, create the admin account, then **Settings > Lidarr**: URL
   `http://lidarr:8686`, Lidarr API key, root folder `/data/media/music`,
   profile **Lossless Preferred**, **Search on add** on. Do **not** use
   **Apply recommended settings** (it rewrites Lidarr's profile/naming).
4. **Downloads Folder** (Aurral's own single-track/flow downloads):
   `/data/media/aurral`.
5. Lidarr **Settings > Connect > Webhook** named `Aurral`:
   `http://aurral:3001/api/webhooks/lidarr`, On Release Import only, header
   `X-Api-Key` = Aurral's key from **Settings > System**, so requesters see
   when albums are available.
6. **Settings > Download clients > slskd**: `http://slskd:5030`, the slskd
   API key (same one Soularr uses), priority 10, **Clean up after runs off**
   (it would clear completed transfers Soularr still needs). slskd reports
   `/data/soulseek/downloads`, which Aurral sees at the same path, so no path
   mapping is needed. This is only for single tracks and playlist/flow tracks
   (Lidarr is album-only); those land in `/data/media/aurral`, outside
   Lidarr. Don't add SABnzbd/qBittorrent: album downloads already go through
   Lidarr, and a second path would only duplicate them.
7. **Settings > Playback > Plex**: **Connect Plex account** (approve the
   plex.tv popup), Server URL `http://plex:32400`, leave **Plex Aurral
   Library path** blank (Plex mounts the same `/data/media` path), set
   **Include tracks from an existing library** to **Music** so playlists reuse
   Lidarr's files, then **Sync to Plex now**. This creates an **Aurral** music
   library in Plex (at `/data/media/aurral`; the compose file sets
   `DOWNLOAD_FOLDER` so Aurral doesn't fall back to `/data/downloads/aurral`,
   which Plex can't see) for flows/playlists, which then show up in Plexamp.
   Use **Music** as the main Plexamp library; **Aurral** only holds
   Aurral-only single tracks/flows. If the
   library dropdown only shows *None*, save first and reopen, or set it with
   `POST /api/settings` `{"integrations":{"plex":{"mainLibrarySectionId":"8"}}}`.

Aurral's recommended Lidarr settings (Davo's community guide) are worse for
this library: its **Aurral - HQ** profile allows only MP3-320 + 16-bit FLAC
(no 24-bit/ALAC/V0) and requires a custom-format score of 1, which rejects
plain "Artist - Album (Year) FLAC" releases. Its FLAC size caps reject
hi-res, its naming uses underscores, and its Compilation/Remix secondary types
bloat the wanted list. Keep **Lossless Preferred**, our naming, and the
Standard/Soundtracks metadata profiles.

Leave Lidarr's **Tag Audio Files** off: retagging writes into files that are
hardlinked to seeding torrents. Aurral then matches artists by name.

Plex picks up new music via Lidarr's Plex Connect (partial scan on import) and
Plex's own filesystem watcher. As a backstop, Plex **Settings > Library >
Scan my library periodically** is on (hourly), since a manual import was once
missed by both.

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
