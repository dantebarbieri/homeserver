# Audiobooks — Audiobookshelf, Storyteller, libro.fm

Services in `compose.media.yml`:

| Service | URL | Role |
|---------|-----|------|
| `audiobookshelf` | `https://audiobookshelf.danteb.com` | Audiobook server + mobile apps (progress sync) |
| `storyteller` | `https://storyteller.danteb.com` | Aligns an EPUB with its audiobook into a "readaloud" EPUB (text highlights while narration plays) |
| `librofm-downloader` | — (no web exposure) | Pulls new DRM-free libro.fm purchases into the Audiobookshelf library daily |

## Ownership model

Each app owns its own files; Storyteller is a read-only consumer.

```
${RAID}/shared/reading/
├── ebooks/                 # Calibre library   (owner: calibre-web)      → storyteller:/library/ebooks:ro
├── audiobooks/             # Author/Title/...  (owner: ABS + librofm)    → storyteller:/library/audiobooks:ro
└── storyteller/
    ├── assets/             # Storyteller-managed files: readalouds, transcoded audio, covers
    └── import/             # Writable fallback import area (see below), normally empty
```

Storyteller's database and scratch space live at `${DATA}/storyteller/data`.
Readalouds are read in the Storyteller app (iOS/Android/web reader); neither
Audiobookshelf nor calibre-web can play media-overlay EPUBs, so they are not
written back into either library.

## First-time setup

### 1. Directories (on the server)

Bind-mount sources that don't exist are created by Docker as root. Create them
first as the `${UID}:${GID}` user from `.env`:

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
4. Install the Audiobookshelf app (iOS/Android) and log in with the server URL.

### 6. Storyteller

1. Open `https://storyteller.danteb.com` and create the admin user.
2. **Settings**:
   - Library → Web URL: `https://storyteller.danteb.com`
   - Automatic import: **leave empty** (pointing it at the Calibre library
     would import every ebook). Import pairs manually as below.
   - Readaloud location: **Storyteller internal folder** (lands in `/assets`).
   - Transcription: `whisper.cpp`, model `tiny` (try `small` if alignment is poor).
3. Install the Storyteller app and log in with the server URL.

### 7. libro.fm downloader

On first start it downloads your whole libro.fm library into
`audiobooks/<First Author>/<Title>/` (M4B, converting MP3-only titles with
ffmpeg), then re-checks daily. To pull a new purchase immediately:

```bash
dce librofm-downloader curl -s http://localhost:8080/update
```

## Making a readaloud

1. Make sure the book exists in both Calibre (EPUB) and Audiobookshelf.
2. Storyteller → **Add book → Import from server** → select the EPUB under
   `/library/ebooks/<Author>/<Title (id)>/` **and** the audiobook folder under
   `/library/audiobooks/<Author>/<Title>/` together so they import as one book.
3. Start **Align**. Watch `dcl storyteller`; the first job builds/downloads
   whisper.cpp. `nvidia-smi` on the host should show the whisper process.

## Validation: first-book end-to-end test (read-only mounts)

Run this once before relying on the read-only setup.

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
dcl -s 1h storyteller | grep -iE 'EROFS|read-only|EACCES|permission|error'
stat -c '%i %h %s %Y %n' "$EPUB" "$AUDIO"; sha256sum "$EPUB" "$AUDIO"
diff /tmp/st-before <(stat -c '%i %h %s %Y %n' "$EPUB" "$AUDIO"; sha256sum "$EPUB" "$AUDIO")
```

**Pass** = import, alignment, and metadata edit all succeed in the UI, no
read-only errors in logs, and the `diff` is empty. Nothing more to do.

## Fallback: writable import folder

If anything in the test fails because the libraries are read-only, keep both
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

Then in Storyteller, delete the failed book and **Import from server** →
`/import/<Author> - <Title>/` (one folder = one book).

**Hardlink caveat:** a hardlink *is* the Audiobookshelf file. If Storyteller
rewrote audio tags in place, the ABS copy would change too. After the metadata
edit, re-run the `sha256sum`/`stat` check against `$SRC_AUDIO`:

- Checksum unchanged → safe (Storyteller didn't touch it, or replaced the
  file, which just breaks the link — link count drops to 1).
- Checksum changed → use `cp -a` instead of `cp -al` for audio from then on.

## Troubleshooting

- **Transcription runs on CPU / `libcuda` not found** — Plex and Tdarr needed
  `LD_LIBRARY_PATH: /usr/local/nvidia/lib64:/usr/local/nvidia/lib` for the
  NixOS CDI driver mounts (see `TDARR.md`). Try the same on `storyteller`.
- **Out of memory during alignment** — lower *Max track length* in Storyteller's
  audio settings.
- **libro.fm login fails** — check `dcl librofm-downloader`; credentials come
  from `LIBRO_FM_USERNAME` / `LIBRO_FM_PASSWORD` in `.env`.
