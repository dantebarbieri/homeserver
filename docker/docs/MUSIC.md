# Music - Lidarr + Plexamp + Navidrome

Lidarr manages artists, albums, and imports. Plex (with **Plexamp**) and
**Navidrome** both serve the same Lidarr library, the same way Plex and
Jellyfin share movies and TV. No duplicate library is needed.

| Component | Address | Role |
|-----------|---------|------|
| Lidarr | `https://lidarr.danteb.com` / internally `http://lidarr:8686` | Library management; optional Prowlarr/download-client integration |
| Plex | Existing Plex server | Music library, accounts, and streaming |
| Plexamp | Install on each listening device | Music-focused playback, gapless, CarPlay, and FLAC support |
| Navidrome | `https://navidrome.danteb.com` / internally `http://navidrome:4533` | Music-only server with a Subsonic API; read-only on the library |

[Plexamp core playback is free](https://www.plex.tv/plexamp/). Plex Pass unlocks
offline downloads, sonic discovery, and other premium features. Navidrome is
free and has its own users, play counts, ratings, and playlists (not synced
with Plex). See [Navidrome](#navidrome) below for clients.

## Library and ownership

| Host path (default `.env`) | Lidarr path | Plex path | Navidrome path |
|---------------------------|-------------|-----------|----------------|
| `/data/shared/media/music` | `/data/media/music` | `/data/media/music` | `/music` (read-only) |
| `/data/shared/imports/music` | `/data/imports/music` | Not mounted | Not mounted |
| `/data/shared/torrents/music` | `/data/torrents/music` | Not mounted | Not mounted |
| `/data/shared/usenet/complete/music` | `/data/usenet/complete/music` | Not mounted | Not mounted |
| `/srv/docker/data/lidarr/config` | `/config` | Not mounted | Not mounted |
| `/srv/docker/data/navidrome` | Not mounted | Not mounted | `/data` (DB, cache) |

This follows the [TRaSH folder structure](https://trash-guides.info/File-and-Folder-Structure/How-to-set-up/Docker/)
already used for movies and TV: the `music` folders under `media`, `torrents`,
and `usenet/{incomplete,complete}` already exist on the server. qBittorrent
mounts `${RAID}/shared/torrents:/data/torrents` and SABnzbd mounts
`${RAID}/shared/usenet:/data/usenet`, so every app reports the same paths.

Lidarr mounts `${RAID}/shared:/data`, like Sonarr/Radarr. Its library,
purchase-import staging, and download paths share one mount and one XFS
filesystem, so Usenet/purchase imports are instant moves. Torrent imports are
copies on purpose (see [Tags, copies and seeding](#tags-copies-and-seeding)).
Never mount `torrents`, `usenet`, and `media/music` into Lidarr
as separate volumes; Docker treats each bind mount as a separate filesystem
and moves silently degrade to slow copy-and-delete. Plex already mounts
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
4. Turn **Rename Tracks** on before the first import, with the formats under
   [Current production configuration](#current-production-configuration).
   Files imported flat and renamed later left Plex with merged albums (see
   [Fixing merged Plex albums](#fixing-merged-plex-albums)). Keep *Tag Audio
   Files with Metadata* off until hardlinks are disabled (section 4 below):
   retagging a hardlinked file corrupts its seeding torrent. Review
   album/release matches before importing, particularly for Japanese editions
   and compilations. Include soundtrack/compilation/EP release types in a
   metadata profile when the default profile excludes the desired release.

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
| Settings > Media Management > Importing | *Use Hardlinks instead of Copy* **disabled**, so torrent imports are copies (see below) |
| Settings > Metadata > Tag Audio Files with Metadata | *All files; keep in sync with MusicBrainz* (`writeAudioTags=sync`), *Embed Cover Art In Audio Files* on, *Scrub Existing Tags* off. Only safe with hardlinks off |
| Prowlarr > Settings > Apps > Lidarr | Prowlarr server `http://prowlarr:9696`, Lidarr server `http://lidarr:8686`, Lidarr API key, default Audio sync categories; test, save, then *Sync App Indexers* |

Use `qbittorrent`, the VPN namespace's network alias, not `qbittorrent-app`.
Never point a download category at `/data/media/music` or the import staging
folder.

**Keep *Use Hardlinks instead of Copy* off.** Lidarr writes tags into the
library copy of every file it manages: on import, when MusicBrainz metadata
changes, and for every file of an artist on *Retag*. A hardlink is the same
data as the seeding torrent, so a tag write also changes the torrent's payload;
the torrent then fails its hash check and stops seeding. Lidarr has no check
for this (it only skips files that map to several tracks). With hardlinks off,
each torrent import is a separate full copy; the cost and the cleanup are in
[Tags, copies and seeding](#tags-copies-and-seeding). Usenet and purchased
imports are moves either way.

Verify after the first torrent import that the two paths are independent
copies: link count `1` and different inodes. Link count `2` with the same inode
is a hardlink, and the next retag corrupts that torrent.

```bash
stat -c '%h %i %n' "/data/shared/torrents/music/<release>/<track>.flac" \
  "/data/shared/media/music/<Artist>/<Album>/<track>.flac"
```

**qbit-manage**: add `music` to the private
`${DATA}/qbit-manage/config/config.yml` `cat:` mapping
(`music: /data/torrents/music`) and to its `nohardlinks:` list, alongside the
video categories. Music torrents are never hardlinked, so qbit-manage always
sees them as `noHL`; that is what eventually deletes the torrent-side copy (see
[Tags, copies and seeding](#tags-copies-and-seeding)). Do the same for
`music-manual: /data/torrents/music-manual`, where `lidarr-maint` parks torrents
Lidarr did not grab. See [qBit Manage inactivity cleanup](QBIT-MANAGE-INACTIVITY.md).

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
scan. Use Plex Music metadata and turn on the library's **Prefer local
metadata** option (stored as `respectTags`; off by default), so Plex trusts the
tags Lidarr writes over its online matches. Do not scan before *Rename Tracks*
is on and every album sits in its own folder: Plex keeps albums merged when
their files are renamed after the first scan (see
[Fixing merged Plex albums](#fixing-merged-plex-albums)). With Plex
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

### 8. Navidrome

Navidrome mounts the music folder read-only and rescans it hourly (plus file
watching), so Lidarr imports show up without any hook. Start it and give it
a host (it isn't reachable from outside until the NPM host exists):

```bash
install -d -m 2775 -o danteb -g docker /srv/docker/data/navidrome
z /srv/homeserver/docker
docker compose up -d navidrome
```

1. In NPM, add proxy host `navidrome.danteb.com` → `navidrome:4533`, with
   WebSockets, Block Common Exploits, and the wildcard certificate. **No
   Authelia**: Navidrome has its own login, and Subsonic apps can't pass SSO
   (the same reason Plex has none).
2. Open it right away: **the first visitor creates the admin account**. Then
   add a regular user for daily listening.
3. Clients (all speak the Subsonic API; server URL
   `https://navidrome.danteb.com`):
   - Windows/macOS/Linux: [Feishin](https://github.com/jeffvli/feishin)
     (also works with Jellyfin) or [Supersonic](https://github.com/dweymouth/supersonic);
   - iPhone: [Amperfy](https://github.com/BLeeEZ/amperfy) or play:Sub;
   - the web UI works in any browser.

Navidrome auto-imports `.m3u` files found in the music folder. Ratings, hearts,
play counts and regular playlists are kept in step with Plex by
[`plex-navidrome-sync`](#plex--navidrome-sync-plex-navidrome-sync).
Homepage widget credentials are in [WIDGET_API_KEYS.md](../../homepage/WIDGET_API_KEYS.md#navidrome--homepage_var_navidrome_user--_token--_salt).

## Current production configuration

The setup steps above describe the initial rollout; production has since moved
on. These are configured in the apps (not in this repo):

| Setting | Value |
|---------|-------|
| Quality profile | `Lossless Preferred`: Lossless group + `MP3 320/V0` fallback, cutoff Lossless, upgrades on. Used by all artists and the Spotify import list (`FLAC Only` is unused) |
| Metadata profiles | `Standard` (Album, EP, Single), `Soundtracks` (Soundtrack/Compilation, for Studio Ghibli) |
| Renaming | On, from the first import: `{Album Title} ({Release Year})/{track:00} - {Track Title}`, multi-disc `{medium:0}-{track:00}`, artist folder `{Artist Name}`. One album is one folder, which Plex's grouping and `plex-album-check` rely on |
| Hardlinks | Off (`copyUsingHardlinks=false`): torrent imports are copies, so tag writes never touch a seeding torrent. See [Tags, copies and seeding](#tags-copies-and-seeding) |
| Tagging | *All files; keep in sync with MusicBrainz* (`writeAudioTags=sync`), *Embed Cover Art In Audio Files* on, *Scrub Existing Tags* off. An artist's *Retag* button (`RetagArtist` command) rewrites its files on demand |
| Plex Music library | *Prefer local metadata* on (`respectTags=true`) |
| Import list | Spotify playlists: monitor specific album, no new albums |
| Connect | Plex Media Server (`plex:32400`), *Update Library* on import. Plex's own change detection misses Lidarr imports |
| Indexers | NZBgeek, The Pirate Bay, 1337x, kickasstorrents, Internet Archive. Torrent minimum seeders `2` (music is thinly seeded) |
| Prowlarr app sync | Lidarr app is `Add and Remove Only` so the per-indexer seeder override survives syncs; add new indexers in Lidarr by hand or let Prowlarr add them |

Prowlarr runs with `DOTNET_SYSTEM_NET_DISABLEIPV6=1`: FlareSolverr solves
Cloudflare over IPv4 and `cf_clearance` is bound to that IP, so Prowlarr must
replay it over IPv4 too (over IPv6 it gets 403 "blocked by CloudFlare").

Internet Archive stalls searches that carry Prowlarr's own User-Agent, so its
indexer uses a repo-managed definition that sends a browser one; see
[PROWLARR.md](PROWLARR.md#internet-archive-user-agent).

Lidarr's MusicBrainz titles for Japanese releases (e.g. Ghibli soundtracks)
are in Japanese while indexers use English, so automatic search rarely matches.
Grab those manually and import with **Wanted > Manual Import**, choosing the
release whose track count matches the files. `lidarr-maint` (below) does this
automatically when the files are already in Lidarr's queue. To move an album
that is already imported onto another edition (for example English titles
instead of Korean), see [Choosing an edition after import](#choosing-an-edition-after-import).

Add hand-grabbed torrents to qBittorrent's `music-manual` category, not
`music`, and import them with *Copy* (a real copy, since hardlinks are off).
Lidarr tracks everything in `music`. If a torrent wasn't grabbed by Lidarr, it
reappears in the queue as "Import failed" on every poll, even after a
successful manual import. A queue *Remove* without removing it from the client
only hides it until the next poll. If one is already in `music`, change its
category to `music-manual`. qBittorrent's automatic torrent management moves
the files on the same filesystem; the library copy is independent of that move.

### Tags, copies and seeding

Lidarr owns the tags and cover art of every library file. It writes them on
import, when MusicBrainz metadata changes, and on *Retag*, so inconsistent or
missing album art in Plexamp is fixed by retagging in Lidarr, not by editing
files in another tagger.

When MusicBrainz has no cover to embed, the optional
[shared artwork fallback](#shared-artwork-fallback-music-cover-fallback)
can add a `cover.jpg` sidecar instead, without changing audio tags.

That is only safe while no library file shares data with a seeding torrent.
In November 2026 a whole-library retag ran while *Use Hardlinks instead of
Copy* was still on. It rewrote about 2,100 library files in place, which also
rewrote the matching torrent payloads: 175 torrents no longer matched their
pieces, so a recheck fails them and they cannot seed correctly. The fix was to
turn hardlinks off, remove those torrents from qBittorrent keeping their files,
and give the remaining torrents independent copies. No library file changed.

With hardlinks off:

- Every torrent import is a second full copy of the album (a real copy, not a
  reflink). It lasts until qbit-manage's `noHL` cleanup removes the torrent
  (at least 14 days seeded and 7 days inactive), and the recycle bin keeps the
  removed data 14 more days. See [QBIT-MANAGE-INACTIVITY.md](QBIT-MANAGE-INACTIVITY.md).
- Music torrents are `noHL` from the moment they are imported. A torrent whose
  import failed looks the same, so resolve stuck imports inside that window.
- Never turn hardlinks back on while tag writing is on.
- `find /data/shared/media/music -type f -links +1` must print nothing. Any
  file it lists is tied to a torrent. Break the tie from the torrent side:
  `cp -a --reflink=auto` the torrent's file to a temporary name in the same
  folder, then `mv -f` it over the original, so the library file is never
  touched, and recheck the torrent in qBittorrent. If a retag already ran, the
  torrent's payload is already corrupt (the recheck fails): remove it from
  qBittorrent and keep its files instead.

### Choosing an edition after import

Lidarr has no language or country preference. It monitors whichever release of
a release group best matched the files at import, and tag writing then puts
that edition's titles into the files. Hisaishi's *The Tale of the Princess
Kaguya* soundtrack imported as the Korean CD edition, so Plex showed Korean
titles; MusicBrainz is not wrong, the release group simply has five editions.
The metadata profile also allows pseudo-releases (translations and
transliterations), which is where the English titles of several soundtracks
come from.

To move an imported album onto another edition without losing its Plex ratings,
play counts or playlist entries (the edition needs the same tracks in the same
order; done this way for 12 albums):

1. Copy the album folder outside the music library first
   (`cp -a --reflink=auto`).
2. Re-import the library files with a `ManualImport` command
   (`POST /api/v1/command`) that names the wanted release for every file: its
   `albumReleaseId`, the matching `trackIds` (from `/track?albumReleaseId=`),
   the file's own `quality`, and `disableReleaseSwitching: true`, with
   `importMode: auto` and `replaceExistingFiles: false`. Files already under
   the artist folder are retagged in place and the monitored release changes;
   nothing is moved or copied. **Never set `replaceExistingFiles: true`:** it
   removes the album's existing files first, which are the files being imported.
3. Refresh the album in Plex: `PUT /library/metadata/<album ratingKey>/refresh`.
   A folder scan alone misses the retag, because FLAC padding keeps the file
   size unchanged.
4. Run Lidarr's `RenameFiles` command for the album (preview it with
   `/rename?artistId=&albumId=`) so the folder and file names follow the new
   titles, then scan the folder in Plex. Plex matches the renamed files to the
   same tracks, so ratings, play counts and playlists stay.

Do not switch the monitored release with a `PUT` on the album instead: it
unlinks the files and rescans, and the rescan can choose the tagged edition
again. Plexamp downloads keep the old titles until they are downloaded again.

## Queue maintenance (`lidarr-maint`)

`lidarr-maint` (`compose.starr.yml`, built from the shared `dockerfiles/arr-maint/` image (common engine in `arr_maint.py`, Lidarr rules in `lidarr.py`))
checks Lidarr's queue every 30 minutes. It only acts on items that have been
stuck for at least 20 minutes (`GRACE_MINUTES`), so Lidarr gets the first try:

| Stuck pattern | Fix |
|---------------|-----|
| Import failed because Lidarr expected another edition (common for soundtracks) | If the file count matches another release and the titles match, manual-import into it (copy for torrents so they keep seeding, move for usenet). Never switches the edition of an album that already has files, since that unlinks them. Lidarr reports a torrent's `protocol` as `TorrentDownloadProtocol` (Radarr and Sonarr use `torrent`), and the helper matches both |
| Completed single audio file rather than an album folder | Import only into an empty, monitored one-track release when Lidarr's manual-import artist, album, release and track IDs agree. Differing remix/live/edit/version qualifiers stay for manual review. Never scans the parent download directory, switches editions or replaces existing files |
| Queue entry still `importFailed` after the helper's own import | Lidarr can fail the manual-import command *after* importing, with a `NullReferenceException` (seen for downloads it rebuilt from its history), and then skips marking the download imported. So a failed command still counts as imported when the album was empty before and now holds every file. A completed command must also have imported every file, and unfinished or aborted commands never count; those are reported for manual review. The helper then clears the leftover entry the same way as the "not grabbed" rows below (torrents move to `music-manual`, usenet entries leave the queue). Until that worked the download is remembered in `${DATA}/lidarr-maint/imported.json` (14 days) and is not imported again |
| Single/EP grabbed for an album (<=4 files for an 8+ track album) | Blocklist + re-search |
| Failed download | Blocklist + re-search |
| Dead torrent: no connected seeds for 24 h (`STALL_HOURS`) and either below 5%, including stuck on "downloading metadata", or partly done with availability below 1 and no activity for 24 h (Lidarr's qBittorrent category, `music`) | Blocklist + re-search |
| "Not grabbed by Lidarr" torrents | Move to `music-manual` (below), download kept |
| "Not grabbed by Lidarr" usenet entries | Remove from the queue (download kept) |
| Completed torrent with no artist match ("Artist name mismatch"), whose files were already imported by hand (hardlink count > 1) | Move the torrent to the `music-manual` qBit category (`/data/torrents/music-manual`), which Lidarr doesn't track, so it keeps seeding. Lidarr v3's queue *Remove* returns HTTP 500 for these unknown-artist items. The rule only recognises hardlinked imports and Lidarr now copies, so a hand import is usually not recognised: the torrent is notified instead, and you move it to `music-manual` yourself |
| Missing albums | `MissingAlbumSearch` at most every 6 h |
| Albums below the Lossless cutoff (MP3, AAC, ...) | `CutoffUnmetAlbumSearch` at most every 24 h (`UPGRADE_SEARCH_HOURS`, `0` disables). Lidarr skips unmonitored and already-queued albums. RSS alone rarely sees lossless releases of older albums |

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

### Track-level fallback (`soularr-fallback`)

Soularr only grabs a folder that matches the whole release from an
"artist album" search. It misses:

- singles that only exist inside album folders;
- album searches that come back empty during one of slskd's 0-result bursts
  (then wait 24 h);
- releases whose first peer never answers (`Requested => Completed, TimedOut`
  in the slskd log: the peer is offline or unreachable, not us).

`soularr-fallback` (`dockerfiles/soularr-fallback`, in `compose.starr.yml`)
picks up every release Soularr has failed (`search_attempts.json` or
`failed_imports.json`). Each hour it takes up to 40 releases and:

1. searches `<artist> <track title>` for the release's two most distinctive
   tracks, then the same under the artist's MusicBrainz aliases (Ye →
   Kanye West, RØYLS → ROYLS; cached in `aliases.json`), then
   `<album> <track title>` with no artist, keeping only folders whose path
   names the album or the artist. Non-Latin titles (Ado's Japanese singles)
   are searched and matched as-is;
2. browses each candidate folder and matches every Lidarr track by title and
   duration (±6 s). Remix, live, instrumental and similar variants are
   rejected unless the track title has them. FLAC is preferred;
3. downloads only the matched files, then ManualImports them (move) with
   explicit track ids.

A peer that hasn't delivered within 12 h, or whose transfer fails, is skipped
and the next one tried (five peers max). Releases with no match are searched
again after 72 h. State is in `/srv/docker/data/soularr-fallback/state.json`.
To set it up, run `install -d -m 2775 -o danteb -g docker
/srv/docker/data/soularr-fallback`, then
`docker compose up -d --build soularr-fallback`. `docker logs soularr-fallback`
shows each grab, import, retry and miss.

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
4. Lidarr **Settings > Connect > Webhook** named `Aurral`:
   `http://aurral:3001/api/webhooks/lidarr`, On Release Import only, header
   `X-Api-Key` = Aurral's key from **Settings > System**, so requesters see
   when albums are available.
5. **Lidarr is the only download path.** Leave every Aurral download client
   off: slskd, yt-dlp (enabled by default), SABnzbd, NZBGet, Deemix and
   Prowlarr. Those clients only fetch single tracks and flow/playlist tracks,
   which Lidarr (album-only) can't, and they save to Aurral's own folder
   outside the Lidarr library. To get a single song, request the single or
   album that contains it.
6. Leave **Settings > Playback > Plex** unconnected. When Plex is connected
   as a playback destination, Aurral always creates and recreates its own
   **Aurral** Plex music library
   (`plexPlaybackDestination.ensureLibrary`), even if it's deleted. Plexamp
   uses the single **Music** library that Lidarr fills. If you connect it by
   mistake, clear it with `POST /api/settings`
   `{"integrations":{"plex":{"url":"","token":"","loginEnabled":false}}}`, then
   delete the Aurral library in Plex.

The compose file still sets `DOWNLOAD_FOLDER=/data/media/aurral`, which keeps
Aurral's (now empty) download folder out of the default
`/data/downloads/aurral`.

Aurral's recommended Lidarr settings (Davo's community guide) are worse for
this library: its **Aurral - HQ** profile allows only MP3-320 + 16-bit FLAC
(no 24-bit/ALAC/V0) and requires a custom-format score of 1, which rejects
plain "Artist - Album (Year) FLAC" releases. Its FLAC size caps reject
hi-res, its naming uses underscores, and its Compilation/Remix secondary types
bloat the wanted list. Keep **Lossless Preferred**, our naming, and the
Standard/Soundtracks metadata profiles.

Leave Lidarr's tag writing on (see [Tags, copies and seeding](#tags-copies-and-seeding)).
Aurral matches Lidarr's files to artists by MusicBrainz tags first and by name
second, so without tags an artist whose name several MusicBrainz artists share
stays unmatched.

Plex picks up new music via Lidarr's Plex Connect (partial scan on import) and
Plex's own filesystem watcher. As a backstop, Plex **Settings > Library >
Scan my library periodically** is on (hourly), since a manual import was once
missed by both.

## Plex ↔ Navidrome sync (`plex-navidrome-sync`)

`plex-navidrome-sync` (in `compose.media.yml`, code in
`dockerfiles/plex-navidrome-sync/`) keeps one Navidrome account in step with
Plex every 15 minutes, both ways. Tracks are matched by their path in the music
folder, so it needs nothing beyond both apps having scanned the file.

| What | How it syncs |
|------|--------------|
| Ratings | A change on either side is copied to the other; if both changed since the last run, the newer one wins. Plex half stars round up (3.5★ → 4★ in Navidrome). |
| Hearts | Plex has no heart, so a Navidrome heart means "2★ or more". Hearting an unrated song rates it 3★ on both sides (as the Spotify/YouTube likes were); un-hearting clears the rating; rating a song 2★+ in Plexamp hearts it in Navidrome. |
| Play counts | Plays added on one side since the last run are added to the other. Plex gets them as normal plays; Navidrome gets them as scrobbles from the `plex-navidrome-sync` player, whose external scrobbling (Last.fm/ListenBrainz) the sync switches off so plays aren't sent twice. |
| Playlists | Regular playlists only (not smart playlists or `.m3u` imports). Paired by name the first time, then by ID. A changed track list replaces the other side's (both changed: the newer wins). Renames and deletions are mirrored; a deleted playlist's track list is saved first under `/srv/docker/data/plex-navidrome-sync/deleted-playlists/`. Songs the other app hasn't scanned yet are left in place. |

On the first run, Plex's playlists overwrite Navidrome's playlists of the same
name, a song rated differently on the two sides takes the more recent rating,
and each side's existing play counts are added to the other once.

Safety: a run that would clear more than `MAX_CLEARS` (default 50) ratings, or
that matches fewer than half the tracks of the previous run (a library mid-rebuild
or a missing mount), stops without changing anything and alerts ntfy
(`homeserver-alerts`). If a Plex or Navidrome item is re-created (a re-import),
it gets its last synced rating back instead of the rating being cleared.

Setup:

```bash
install -d -m 2775 -o danteb -g docker /srv/docker/data/plex-navidrome-sync
z /srv/homeserver/docker
# add NAVIDROME_PASSWORD (and NAVIDROME_USER if it isn't danteb) to .env
docker compose build plex-navidrome-sync
docker compose run --rm -e DRY=1 -e ONCE=1 plex-navidrome-sync   # preview only
docker compose up -d plex-navidrome-sync
```

The Plex token is read from Plex's `Preferences.xml` (mounted read-only).
Until both `NAVIDROME_USER` and `NAVIDROME_PASSWORD` are set, the container
logs that it is waiting and stays healthy without syncing, writing a success
timestamp, or sending failure alerts. Once configured, health requires a
successful run within two intervals plus 15 minutes; missing or invalid
success state is unhealthy. After adding credentials to `.env`, preview
first, then use `docker compose up -d plex-navidrome-sync` to recreate the
waiting container with the new environment (a restart alone won't load it).
State (the last synced value of every track and playlist) is in
`/srv/docker/data/plex-navidrome-sync/state.json`; deleting it makes the next
run behave like the first one again, including copying play counts once more.

## Shared artwork fallback (`music-cover-fallback`)

This opt-in Docker service checks downloaded Lidarr albums once a day. It adds
`cover.jpg` beside the tracks so both Plex and Navidrome can use it; it does not
need the Navidrome password or the ratings-sync service. Existing image files
(even nonstandard names), embedded artwork and Lidarr-provided covers are left
alone. Lidarr remains the sole audio tag writer.

The source order is Cover Art Archive (the selected MusicBrainz release, then
its release group), then Apple Music and Deezer. Store matches require the same
artist, exact album/edition title, full track count, ordered track titles and
durations within five seconds. Apple's trailing ` - Single`/` - EP` labels are
ignored; deluxe/live/remix distinctions are not. Different release dates are
allowed for reissues only when those checks pass. If matched editions/stores
have visibly different covers, the job reports the conflict instead of choosing.
Spotify is not queried: these public catalog APIs need no additional account
or token. Only public artist/album search terms are sent to the stores.

Safety and limitations:

- No audio file is written, moved or retagged, so torrent payloads are untouched.
  Albums must follow the existing `Artist/Album/track` layout; flat imports,
  split folders and symlinks are refused.
- It verifies image bytes, size and dimensions, converts to JPEG, and publishes
  the complete file atomically without overwriting an existing `cover.jpg`.
  A source outage is logged as an error, never interpreted as "no MusicBrainz art".
- Source links, MusicBrainz IDs and SHA-256 hashes are kept under
  `/srv/docker/data/music-cover-fallback/state.json`. `report.json` lists writes,
  unresolved matches and errors. New unresolved cases alert through ntfy;
  unchanged cases remind weekly. Failed runs alert; an overdue successful run
  makes the container unhealthy.
- A Plex partial scan and missing-art metadata refresh follow each new cover.
  Existing/locked Plex posters are not replaced, including the six manual fixes.
  Failed refreshes are retried without downloading or rewriting the cover again.
  Navidrome picks up the sidecar through its watcher/hourly scan. Clients with
  downloaded/cached artwork may still need a refresh or re-download.
- Plex's **Album Art** must be **Both Plex Music and Local Files** (the current
  setting) or **Local Files Only**. Navidrome's default `CoverArtPriority`
  already prefers `cover.*`; no global preference is changed by the script.
- This is a conservative fallback, not an artwork upgrader: it never replaces
  a fallback with later MusicBrainz art automatically. To undo a generated cover,
  check its recorded hash before removing that specific file and refreshing the
  album. Do not remove manually edited covers.

The service is **disabled by default**, and remains idle/healthy until enabled.
After merging, create its writable state directory and preview from the main
Compose entry point. Plex and Lidarr need to join the new `music-maintenance`
network once; recreating these two services briefly interrupts them:

```bash
install -d -m 2775 -o danteb -g docker /srv/docker/data/music-cover-fallback
z /srv/homeserver/docker
docker compose build music-cover-fallback
docker compose up -d plex lidarr
docker compose run --rm --no-deps -e DRY=1 -e ONCE=1 music-cover-fallback
# After reviewing the proposed matches, set MUSIC_COVER_FALLBACK_ENABLED=1 in .env.
docker compose up -d music-cover-fallback
docker compose logs --tail=50 music-cover-fallback
```

`DRY=1` reads APIs/files and validates candidate images, but writes no covers,
state, notifications or Plex changes. `ONCE=1` exits nonzero on errors. Concurrent
apply instances are refused by a state-directory lock. To preview again while
enabled, use the same read-only command above; do not run another apply instance.

Focused regression checks (no live server calls):

```bash
uv run --no-project --with-requirements docker/dockerfiles/music-cover-fallback/requirements.txt \
  python -B -m unittest discover -s docker/tests -p 'test_music_cover_fallback.py'
```

## Fixing merged Plex albums

A merged album shows mixed cover art in Plexamp, or one album page that lists
the tracks of several albums. Retagging in Lidarr does not fix it, because the
merge is in Plex's library, not in the files.

**Cause.** Plex keeps the albums it built from a scan even after the files are
renamed. Lidarr's first imports (October 24, 2026) were flat because *Rename
Tracks* was off; Plex scanned them, then the bulk rename ran and Plex kept the
merged albums. A few other albums were separate folders that Plex's agent
matched into one while *Prefer local metadata* was off.

**Prevention.** Turn *Rename Tracks* on before the first import, turn *Prefer
local metadata* on, and don't let Plex scan flat imports. Both settings live in
the apps, not in this repo, and neither repairs an album that is already
merged. Lidarr's naming puts each album in its own `<Artist>/<Album>/` folder,
so one Plex album should be one folder.

**Detection.** `plex-album-check` (`nixos/modules/plex-album-check.nix`) runs
daily at 06:30 (up to 10 minutes later). It opens Plex's database read-only and
groups the tracks by album: an album built from more than one folder is a merge
(a trailing disc folder such as `CD 2` does not count). A new merge sends an
ntfy notice to `homeserver-alerts` ("Merged Plex albums on homeserver") at once,
a merge that is still unrepaired repeats it weekly, and a clean library stays
silent. If Plex returns no tracks the unit fails, which raises the usual ntfy
failure alert. It remembers what it has reported in `/var/lib/plex-album-check`.
Run it on demand:

```bash
sudo systemctl start plex-album-check
journalctl -u plex-album-check -n 30 --no-pager
```

**Repair.** `PUT /library/metadata/<id>/split` does nothing for merges the
scanner made, so make Plex forget the affected albums and scan again. No media
file is moved or changed. The steps use Plex's API (`X-Plex-Token` from
`Preferences.xml`; the Music section id is `8` here):

1. **Snapshot first.** Record the ratings, play counts and playlist contents
   (in order) of the affected tracks. Deleting an item drops its playlist
   entries.
2. **Drop the albums.** Put a `.plexignore` containing `*` in each affected
   album folder, then partial-scan the parent folder:
   `GET /library/sections/8/refresh?path=<parent folder>`. Plex removes the items
   at once because *Empty trash automatically after every scan* is on (the
   default); if it was turned off, empty the trash.
3. **Recreate them.** Delete the `.plexignore` files and scan the same folders
   again. Plex rebuilds the albums grouped by folder, with new ids. Poll
   `GET /activities` to see when a scan has finished.
4. **Restore your data.**
   - Ratings and play counts of tracks Plex matched online come back by
     themselves. Tracks with a `local://` guid lose their ratings: re-rate them
     by path with
     `PUT /:/rate?key=<ratingKey>&identifier=com.plexapp.plugins.library&rating=<0-10>`
     (10 is five stars). Play counts cannot be restored exactly.
   - Re-add playlist entries with
     `PUT /playlists/<id>/items?uri=server://<machineIdentifier>/com.plexapp.plugins.library/library/metadata/<ratingKey>,<ratingKey>,...`,
     about 120 keys per call. To fix an order, re-add or move items to the end
     of the playlist: about 20 or more consecutive "move after" calls into one
     gap scramble it.

Never use `DELETE /library/metadata/<id>` for this: Plex mounts the library
read-write, so with media deletion allowed it deletes the files from disk.
Never write to Plex's database either; the check only ever opens it read-only.

## Acceptance checks

- Lidarr requires login through NPM; its Homepage widget and optional Prowlarr
  connection succeed with the API key.
- Import one purchased FLAC album and verify its edition, tags, ownership,
  and destination under `/data/shared/media/music`.
- Plex indexes it without disturbing existing movie/TV libraries.
- Play it in Plexamp on iPhone and both desktops; check Direct Play/FLAC.
- If using Plex Pass downloads, verify playback in airplane mode.
- For optional automated downloads, confirm a `music`-category torrent lands
  in `/data/torrents/music`, imports into the music root as an independent
  copy (link count 1), keeps seeding, and the FLAC-only profile rejects lossy
  releases.
- `find /data/shared/media/music -type f -links +1` lists nothing.
- `sudo systemctl start plex-album-check` succeeds, and
  `journalctl -u plex-album-check -n 5 --no-pager` says "No Plex album spans
  more than one folder".

## References

- [Lidarr quick start](https://wiki.servarr.com/lidarr/quick-start-guide)
- [Importing an existing library](https://wiki.servarr.com/lidarr/importing-existing-library)
- [Hotio Lidarr image](https://hotio.dev/containers/lidarr/)
- [Plexamp features and downloads](https://www.plex.tv/plexamp/)
- [Homepage Lidarr widget](https://gethomepage.dev/widgets/services/lidarr/)
