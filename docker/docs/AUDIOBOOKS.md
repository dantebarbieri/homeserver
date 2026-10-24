# Audiobooks — Audiobookshelf, Storyteller, BookBridge, libro.fm

Services in `compose.media.yml`:

| Service | URL | Role |
|---------|-----|------|
| `audiobookshelf` | `https://audiobookshelf.danteb.com` | Audiobook server + mobile apps (progress sync) |
| `storyteller` | `https://storyteller.danteb.com` | Aligns an EPUB with its audiobook into a "readaloud" EPUB (text highlights while narration plays) |
| `bookbridge` | `https://bookbridge.danteb.com` (dashboard), `https://kosync.danteb.com` (KOReader sync) | Progress-sync hub between KOReader, Audiobookshelf, and Storyteller (see [BookBridge](#bookbridge--koreader-progress-sync)) |
| `librofm-downloader` | — (no web exposure) | Pulls new DRM-free libro.fm purchases into the Audiobookshelf library daily |

## Ownership model

Each app owns its own files; Storyteller and BookBridge are read-only consumers.

```
${RAID}/shared/reading/
├── ebooks/                 # Calibre library   (owner: calibre-web)      → storyteller:/library/ebooks:ro, bookbridge:/books:ro
├── audiobooks/             # Author/Title/...  (owner: ABS + librofm)    → storyteller:/library/audiobooks:ro
└── storyteller/
    ├── assets/             # Intended Storyteller asset dir; currently unused (see below)
    └── import/             # Writable fallback import area (see below), normally empty
```

Storyteller's database and scratch space live at `${DATA}/storyteller/data`.
Storyteller currently ignores `STORYTELLER_ASSETS_DIR` and writes its assets
(readalouds, transcoded audio, transcriptions, covers) to
`${DATA}/storyteller/data/assets`, so that is what BookBridge mounts read-only
at `/storyteller/assets`.
Readalouds are read in the Storyteller app (iOS/Android/web reader); neither
Audiobookshelf nor calibre-web can play media-overlay EPUBs, so they are not
written back into either library.

## First-time setup

### 1. Directories (on the server)

Bind-mount sources that don't exist are created by Docker as root. Create them
first as the `${HOST_UID}:${HOST_GID}` user from `.env`:

```bash
sudo install -d -o 1000 -g 1000 \
  /data/shared/reading/audiobooks \
  /data/shared/reading/storyteller/assets \
  /data/shared/reading/storyteller/import \
  /srv/docker/data/audiobookshelf/config \
  /srv/docker/data/audiobookshelf/metadata \
  /srv/docker/data/storyteller/data \
  /srv/docker/data/librofm-downloader
```

### 2. `.env`

```bash
STORYTELLER_SECRET_KEY='<openssl rand -base64 32>'
LIBRO_FM_USERNAME='you@example.com'
LIBRO_FM_PASSWORD='...'
HOMEPAGE_VAR_AUDIOBOOKSHELF_KEY=''   # fill in after step 4
```

### 3. Start

```bash
z /srv/homeserver/docker
docker compose pull audiobookshelf storyteller librofm-downloader
docker compose up -d audiobookshelf storyteller librofm-downloader
dcl storyteller librofm-downloader
```

The Storyteller CUDA image is large (~10+ GB); the first pull takes a while.

### 4. Nginx Proxy Manager

No host ports and no firewall/router changes — everything goes through NPM.
Both apps have their own auth and mobile apps that can't do Authelia's
forward-auth flow, so **do not** add Authelia.

| Proxy host | Forward to | Options |
|------------|-----------|---------|
| `audiobookshelf.danteb.com` | `http://audiobookshelf:80` | **WebSockets on** (required for socket.io), Block Common Exploits on, SSL |
| `storyteller.danteb.com` | `http://storyteller:8001` | WebSockets on, Block Common Exploits **off** (chunked audiobook uploads), SSL |

Redirection hosts (301): `audiobooks`, `abs` → `audiobookshelf`;
`readaloud` → `storyteller`.

### 5. Audiobookshelf

1. Open `https://audiobookshelf.danteb.com` and create the root user.
2. **Libraries → Add Library**: name `Audiobooks`, type *Books*, folder `/audiobooks`.
   Leave the folder watcher enabled so libro.fm downloads appear automatically.
3. **Settings → API Keys → Add API Key** for Homepage
   (see `homepage/WIDGET_API_KEYS.md`), then `dcr homepage`.
4. Install a client and log in with the server URL. Android: the official app
   on Google Play. iOS: the official app is TestFlight-only
   (<https://testflight.apple.com/join/wiic7QIW>, usually full), so use a
   third-party App Store client such as **AudioBooth** (open source) or Plappa.

### 6. Storyteller

1. Open `https://storyteller.danteb.com` and create the admin user.
2. **Settings**:
   - Library → Web URL: `https://storyteller.danteb.com`
   - Automatic import: **leave empty** (pointing it at the Calibre library
     would import every ebook). Import pairs manually as below.
   - Readaloud location: **Storyteller internal folder** (lands in `/assets`).
   - Transcription: `whisper.cpp`, model `tiny` (try `small` if alignment is poor).
3. Install **Storyteller Reader** (official, App Store / Google Play) and log
   in with the server URL. Keep the app in the foreground while downloading.

### 7. libro.fm downloader

On first start it downloads your whole libro.fm library into
`audiobooks/<First Author>/<Title>/` (M4B, converting MP3-only titles with
ffmpeg), then re-checks daily. To pull a new purchase immediately:

```bash
dce librofm-downloader curl -s http://localhost:8080/update
```

At `LOG_LEVEL: INFO` the downloader logs almost nothing about downloads
(per-book messages are verbose-only), so check progress on disk instead:

```bash
find /data/shared/reading/audiobooks -type f | head
dce librofm-downloader curl -s http://localhost:8080/history
```

If a new purchase doesn't appear, confirm it's in the downloader's copy of the
library (`sudo grep -o '"title":"[^"]*"' /srv/docker/data/librofm-downloader/libro_library.json`)
and re-run `/update` — libro.fm can take a few minutes to list new purchases.

## Making a readaloud

1. Make sure the book exists in both Calibre (EPUB) and Audiobookshelf.
2. Storyteller → **Add book → Import from server** → select **only** the EPUB
   under `/library/ebooks/<Author>/<Title (id)>/`.
3. **Import from server** again → select **only** the audiobook under
   `/library/audiobooks/<Author>/<Title>/`.
4. In the library, select both "<Title>" entries → **Merge**.
5. Start **Align**. Watch `dcl storyteller`; `nvidia-smi` on the host should
   show `whisper-cli` while it transcribes.

Why separately: selecting the EPUB and audiobook in one import adds only the
EPUB, and the audiobook fails with `UNIQUE constraint failed: book.uuid`
(upstream [#867](https://gitlab.com/storyteller-platform/storyteller/-/issues/867)).
The UI just returns to the home page, so check `dcl storyteller` if a book
seems missing.

**Expected log errors:** after a merge or metadata edit, Storyteller tries to
write metadata back into the source EPUB and logs
`ERROR: Failed to write metadata to epub … EROFS: read-only file system …, skipping`.
This is the read-only mount protecting Calibre's files (calibre-web's
`metadata.db` stays authoritative). It is harmless — alignment continues and
the readaloud is built in Storyteller's own folder.

## Validation: first-book end-to-end test (read-only mounts)

**Status: passed (2026-10-16)** with three libro.fm books — import (via the
separate-import + merge workaround), GPU alignment, and readaloud playback with
synced highlighting in Storyteller Reader all worked on the read-only mounts.
Re-run this if Storyteller changes how it handles source files.

```bash
EPUB='/data/shared/reading/ebooks/<Author>/<Title (id)>/<file>.epub'
AUDIO='/data/shared/reading/audiobooks/<Author>/<Title>/<file>.m4b'
stat -c '%i %h %s %Y %n' "$EPUB" "$AUDIO" > /tmp/st-before
sha256sum "$EPUB" "$AUDIO" >> /tmp/st-before
```

1. Import the pair (above) and align it to completion.
2. Edit the book's metadata in Storyteller (e.g. title, series, cover) and save.
3. Download the readaloud and open it in the Storyteller app; confirm
   highlighting follows the narration.
4. Check for failures and that the source files are untouched:

```bash
docker compose logs --since 1h storyteller | grep -iE 'EROFS|read-only|EACCES|permission|error'
stat -c '%i %h %s %Y %n' "$EPUB" "$AUDIO"; sha256sum "$EPUB" "$AUDIO"
diff /tmp/st-before <(stat -c '%i %h %s %Y %n' "$EPUB" "$AUDIO"; sha256sum "$EPUB" "$AUDIO")
```

**Pass** = import, alignment, and metadata edit all succeed in the UI, the
readaloud plays with synced highlighting, and the `diff` is empty. The
"Failed to write metadata to epub … EROFS … skipping" errors are expected (see
above); any *other* read-only error that stops a job is a failure.

## Fallback: writable import folder

If a job (import, alignment, readaloud build) actually fails because the
libraries are read-only, keep both
libraries read-only and import from `/import` instead
(`${RAID}/shared/reading/storyteller/import`, already mounted read-write).
Copy the EPUB (Storyteller may rewrite it) and hardlink the audio — it's the
same RAID filesystem, so this is instant and uses no extra space:

```bash
SRC_EPUB='/data/shared/reading/ebooks/<Author>/<Title (id)>/<file>.epub'
SRC_AUDIO='/data/shared/reading/audiobooks/<Author>/<Title>'
DEST='/data/shared/reading/storyteller/import/<Author> - <Title>'

install -d "$DEST"
cp "$SRC_EPUB" "$DEST/"
cp -al "$SRC_AUDIO/." "$DEST/"   # hardlinks every audio file (and subfolders)
```

Then in Storyteller, delete the failed book and import the EPUB and audio from
`/import/<Author> - <Title>/` separately, then merge (see
[Making a readaloud](#making-a-readaloud)).

**Hardlink caveat:** a hardlink *is* the Audiobookshelf file. If Storyteller
rewrote audio tags in place, the ABS copy would change too. After the metadata
edit, re-run the `sha256sum`/`stat` check against `$SRC_AUDIO`:

- Checksum unchanged → safe (Storyteller didn't touch it, or replaced the
  file, which just breaks the link — link count drops to 1).
- Checksum changed → use `cp -a` instead of `cp -al` for audio from then on.

## BookBridge — KOReader progress sync

[BookBridge](https://github.com/cporcellijr/bookbridge)
([docs](https://cporcellijr.github.io/bookbridge/), formerly abs-kosync-bridge)
is its own KOSync server: KOReader (e.g. on the jailbroken Kindle) pushes
reading position to it, and it maps that position to/from Audiobookshelf
listening progress and Storyteller. Calibre-web stays the ebook library;
BookBridge only reads it.

It runs in **split-port mode** (`KOSYNC_PORT=5758`):

| Port | Host | Serves | Auth |
|------|------|--------|------|
| 5757 | `bookbridge.danteb.com` | Dashboard, Settings, matcher, admin API | BookBridge's own login (no Authelia — it has solid built-in multi-user auth) |
| 5758 | `kosync.danteb.com` | KOSync protocol + Bridge Sync plugin routes only | KoSync username/password per reader. **Never** Authelia — KOReader can't do browser SSO |

Data (`database.db` + `secret.key`, the key that encrypts every stored
credential) lives in `${DATA}/bookbridge/data` — back them up together. The
container runs as root (the image has no PUID support), so the library mounts
are read-only.

### 1. Directory and `.env`

```bash
sudo install -d -o 1000 -g 1000 /srv/docker/data/bookbridge/data
```

`BOOKBRIDGE_KOSYNC_TRUSTED_PROXIES` → `KOSYNC_TRUSTED_PROXIES`: NPM's own
addresses on the proxy network, so the KoSync login lockout (5 bad passwords →
1 minute) counts per device instead of per NPM. Get them with:

```bash
docker inspect -f '{{with index .NetworkSettings.Networks "compose_proxy"}}{{.IPAddress}},{{.GlobalIPv6Address}}{{end}}' nginxproxymanager
```

This prints the `proxy`-network pair; use it as-is (e.g. `BOOKBRIDGE_KOSYNC_TRUSTED_PROXIES='172.18.0.5,fd00:…::5'`).
Leaving it empty is safe — every device just shares one lockout bucket. If NPM's
IP changes after a recreate, update it (the fallback is the same shared bucket).

### 2. Start

```bash
z /srv/homeserver/docker
docker compose pull bookbridge
docker compose up -d bookbridge homepage
dcl bookbridge
```

### 3. Nginx Proxy Manager

No host ports, firewall, or router changes. No Authelia rules.

| Proxy host | Forward to | Options |
|------------|-----------|---------|
| `bookbridge.danteb.com` | `http://bookbridge:5757` | WebSockets on, Block Common Exploits on, SSL (Force SSL, HTTP/2) |
| `kosync.danteb.com` | `http://bookbridge:5758` | WebSockets off, Block Common Exploits **off** (plugin uploads JSON sessions/highlights), SSL (Force SSL, HTTP/2), no access list (the Kindle syncs from anywhere) |

### 4. First run (dashboard)

1. Open `https://bookbridge.danteb.com`; the first visit creates the admin account.
2. **Settings → Integrations** (server-wide), then **Save Settings** (the app restarts):
   - **Audiobookshelf**: Enable, Server URL `http://audiobookshelf:80`.
   - **KOReader / KoSync**: Enable, Hash Method `content`. Leave *Target KOSync URL*
     empty (built-in server). *Trusted proxy addresses* comes from `.env`.
   - **Storyteller**: Enable, API URL `http://storyteller:8001`.
   - Leave Grimmory, BookOrbit, Kavita, CWA, BookFusion, Readest off.
     Hardcover is optional.
3. **Settings → System**: Storyteller Assets Path `/storyteller`.
4. **Account → My Integrations** (per reader), using each card's **Test** button:
   - Audiobookshelf: API token (ABS → Settings → API Keys) and Library ID (**Find IDs**).
   - KOReader / KoSync: pick a username and password for the device.
   - Storyteller: your Storyteller username/password.
5. Create mappings via **Suggestions → Scan Library** or **Add / Update Book**.

### 5. KOReader (Kindle)

1. **Tools → Progress sync → Custom sync server**: `https://kosync.danteb.com`
   (base URL only, no `/api` or `/koreader` suffix), then **Login** with the
   KoSync credentials from My Integrations. **Register** only works for an
   account that already exists in BookBridge.
2. Optional: **My Account → Connect a KOReader device** offers the Bridge Sync
   plugin (highlights/notes, reading stats, status sync). Unzip into
   `koreader/plugins/`, restart KOReader, and set the same server URL and login
   under **Tools → Bridge Sync**.

"Unknown server error" on login means the URL or network path is wrong, not
the password.

## Troubleshooting

- **Transcription runs on CPU / `libcuda` not found** — Plex and Tdarr needed
  `LD_LIBRARY_PATH: /usr/local/nvidia/lib64:/usr/local/nvidia/lib` for the
  NixOS CDI driver mounts (see `TDARR.md`). Try the same on `storyteller`.
- **Out of memory during alignment** — lower *Max track length* in Storyteller's
  audio settings.
- **libro.fm login fails** — check `dcl librofm-downloader`; credentials come
  from `LIBRO_FM_USERNAME` / `LIBRO_FM_PASSWORD` in `.env`.
