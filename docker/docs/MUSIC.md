# Music: Lidarr + Navidrome

| Piece | Container | URL | Role |
|-------|-----------|-----|------|
| Lidarr | `lidarr` (`compose.starr.yml`) | `https://lidarr.danteb.com` | The Starr app for music: monitors artists, grabs releases, renames/tags, imports |
| Navidrome | `navidrome` (`compose.media.yml`) | `https://music.danteb.com` | Music server with web player + Subsonic API for phone/desktop apps |
| Plex / Jellyfin | existing | existing | Can also serve the same library (Plexamp, Finamp) |

## Library layout

```
/data/shared/media/music/           # Lidarr root folder; Navidrome/Plex/Jellyfin read it
/data/shared/imports/music/         # Drop zone for purchased downloads (mora, Bandcamp, Qobuz…)
```

Container paths:

| Container | Host path | Container path |
|-----------|-----------|----------------|
| lidarr | `/data/shared` | `/data` (same as Radarr/Sonarr — hardlinks work from `/data/torrents` and `/data/usenet`) |
| navidrome | `/data/shared/media/music` | `/music` (read-only) |
| plex, jellyfin | `/data/shared/media` | `/data/media` → music is at `/data/media/music` |

Create the folders once on the server:

```bash
# Match UID/GID in docker/.env
sudo install -d -o <UID> -g <GID> -m 2775 /data/shared/media/music /data/shared/imports/music
```

Tdarr is not affected — its libraries are explicit folders and none point at `music`.

## Lidarr setup

1. `docker compose up -d lidarr`, open `https://lidarr.danteb.com`, set up
   Forms authentication (same as Radarr/Sonarr).
2. **Settings → Media Management → Root Folders**: add `/data/media/music`.
   Enable *Use Hardlinks instead of Copy*.
3. **Settings → Download Clients**: add qBittorrent (`qbittorrent:8080`,
   category `lidarr`) and SABnzbd (`sabnzbd:8080`, category `music`) — same
   hosts Radarr/Sonarr use.
4. **Prowlarr → Settings → Apps**: add Lidarr (`http://lidarr:8686`, API key
   from Lidarr → Settings → General). Prowlarr pushes music-capable indexers.
5. **Settings → Profiles → Quality**: create a *Lossless* profile that allows
   only `FLAC` and `FLAC 24bit` (put 24-bit on top), cutoff `FLAC 24bit`, and
   make it the default. Recyclarr/TRaSH does not manage Lidarr profiles.
6. **Settings → Metadata**: enable *Write Audio Tags* → *For new downloads*
   if you want Lidarr to normalize tags to MusicBrainz.

Lidarr is MusicBrainz-driven: an album must exist in MusicBrainz for Lidarr
to match it. Japanese releases are usually there, but check the exact edition.

## Purchased FLACs (mora, Bandcamp, Qobuz, HDtracks…)

Buying is the cleanest way to get guaranteed-lossless masters. Stores that sell
DRM-free FLAC downloads:

| Store | Notes |
|-------|-------|
| [mora](https://mora.jp/) | Sony-affiliated Japanese store; huge J-pop/anime catalog, many 24-bit hi-res. Downloads via the mora downloader app. |
| [OTOTOY](https://ototoy.jp/) | Japanese indie/idol/anime; FLAC and hi-res. |
| [Bandcamp](https://bandcamp.com/) | FLAC for everything; most money goes to the artist. |
| [Qobuz](https://www.qobuz.com/) store | Western catalog, 16/24-bit FLAC purchases (separate from the subscription). |
| [HDtracks](https://www.hdtracks.com/), [7digital](https://www.7digital.com/), [Presto Music](https://www.prestomusic.com/) | Hi-res, classical/jazz strength (Presto). |
| CDs | Rip with EAC/XLD → FLAC; still often the cheapest lossless. |

Import workflow:

1. Copy the purchased album folder into `/data/shared/imports/music/` (e.g. via
   Syncthing, Nextcloud, or `scp`).
2. Lidarr → **Wanted → Manual Import** (or *Library Import* for a new artist),
   browse to `/data/imports/music`, match each folder to the MusicBrainz release,
   and import. Lidarr moves/renames it into `/data/media/music` and adds the
   artist if needed.
3. Navidrome picks it up on its hourly scan (or **Settings → Scan** now).

Optional: unmonitored artists you only buy manually can still be added in
Lidarr with *Monitor: None* so imports rename consistently without Lidarr
searching indexers for them.

## Navidrome setup

1. `docker compose up -d navidrome`, open `https://music.danteb.com` — the first
   login creates the admin account.
2. NPM proxy host: `music.danteb.com` → `navidrome:4533`, **WebSockets on**,
   Block Common Exploits on. **No Authelia** — Navidrome has its own login, and
   Subsonic apps can't pass through SSO. Add a redirection host
   `navidrome.danteb.com` → `music.danteb.com`.
3. Create a normal (non-admin) user per person for apps.
4. Homepage widget credentials: see `homepage/WIDGET_API_KEYS.md`.

Navidrome serves FLAC untouched by default. Apps can request on-the-fly
transcoding (Opus/MP3) on cellular; the image includes ffmpeg.

## Player apps

Navidrome speaks the Subsonic/OpenSubsonic API, so any Subsonic client works:

| Platform | App | Why |
|----------|-----|-----|
| Android | **Symfonium** (paid) | Best-in-class: offline cache, gapless, ReplayGain, Android Auto, bit-perfect USB DAC output. Also supports Plex/Jellyfin. |
| iOS | **Arpeggi**, **Amperfy**, **play:Sub**, **substreamer** | Arpeggi is the most polished; Amperfy is free/open source with offline + CarPlay. |
| Desktop | **Feishin** | Modern open-source client for Navidrome and Jellyfin. |
| Web | Navidrome's built-in UI | Good enough for casual use; supports sharing links. |

If you'd rather stay in the Plex ecosystem, **Plexamp** (iOS/Android/desktop)
is excellent — gapless, loudness leveling, sonic analysis "radios" — and needs
only a *Music* library in Plex pointing at `/data/media/music`. Jellyfin users
can do the same with **Finamp**. All three servers can share the one library.
