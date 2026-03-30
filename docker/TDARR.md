# Tdarr Configuration Guide — HEVC Library Compression

Compress existing x264 TV show libraries to HEVC (x265) using CPU-only
encoding (`libx265`) for maximum perceptual quality on an AMD EPYC server.
Movie libraries follow the same pattern and are documented for future use.

**Hardware:** AMD EPYC CPU, RTX 2070 SUPER (GPU decode only — not used for
encoding). **Goal:** Best quality-per-bit, not speed.

---

## 1. Codec Choice: HEVC (x265) via libx265

### Why HEVC and not AV1?

| Factor | HEVC / x265 | AV1 |
|--------|-------------|-----|
| **Playback support** | Universal — every TV, phone, and app since ~2016 | Growing, but spotty on pre-2022 hardware |
| **GPU decode on RTX 2070 SUPER** | ✅ Full hardware decode | ❌ No AV1 decode (requires RTX 3000+) |
| **Plex / Jellyfin transcoding** | GPU-accelerated on your card | Would require CPU decode → heavy server load |
| **Space savings vs x264** | 40–60 % smaller at same quality | 50–70 % smaller (marginal extra vs HEVC) |
| **Encoding maturity** | libx265 is battle-tested | libsvtav1 is good but newer |

**Bottom line:** HEVC gives massive space savings with universal compatibility
on your hardware. AV1 would save ~15 % more but your RTX 2070 SUPER can't
hardware-decode it — Plex/Jellyfin would CPU-transcode for any client that
can't direct-play AV1. Not worth the trade-off.

### Why CPU (libx265) instead of NVENC?

CPU (`libx265`) produces significantly better quality-per-bit than NVENC,
especially at lower bitrates. On an EPYC with many cores, `slow` preset is
practical. NVENC is fast but wastes ~20–30 % more bits for the same VMAF
score. Since this is a background batch job, CPU encoding is the right call.

### What about AV2?

AV2's spec was finalized by AOMedia in late 2025 and a reference encoder
(AVM) exists, but:

- **Zero hardware decode support** in any shipping GPU, TV, or phone
- **No optimized software decoder** (no equivalent of dav1d yet)
- **Tdarr has no AV2 support** — ffmpeg doesn't have a production AV2 encoder
- Real-world adoption is years away (late 2020s at earliest)

AV2 is irrelevant for home media use today. Revisit in 2028+.

---

## 2. Path Reference

The Docker volume mount is:

```
${RAID}/shared/media:/data/media       # RAID=/data → /data/shared/media on host
```

All media lives under this single mount. **No additional volume mounts are
needed.**

### Libraries to create

| Library | Host path | Container path | Arr notification |
|---------|-----------|---------------|------------------|
| **TV Shows** | `/data/shared/media/tv` | `/data/media/tv` | Sonarr |
| **Anime TV** | `/data/shared/media/anime/tv` | `/data/media/anime/tv` | Sonarr |
| **Indian TV** | `/data/shared/media/indian/tv` | `/data/media/indian/tv` | Sonarr |
| Movies *(future)* | `/data/shared/media/movies` | `/data/media/movies` | Radarr |
| Anime Movies *(future)* | `/data/shared/media/anime/movies` | `/data/media/anime/movies` | Radarr |
| Indian Movies *(future)* | `/data/shared/media/indian/movies` | `/data/media/indian/movies` | Radarr |

---

## 3. Docker Compose Prerequisites

The Tdarr service is defined in `docker/compose.starr.yml`. Only minor
environment tuning is needed — **no volume mount or network changes required**.

### Worker tuning

With an EPYC CPU you can run more than 2 transcode workers. Each `libx265
slow` encode **can efficiently use ~4 threads**, so a good starting point is
**1 worker per 4 physical cores**:

```yaml
# compose.starr.yml → tdarr → environment
transcodecpuWorkers: 4    # bump from 2 — tune based on core count
healthcheckcpuWorkers: 4  # health checks are lightweight
```

> **Example:** 16-core EPYC → 4 workers. 32-core → 6–8 workers.
> Monitor CPU usage after starting and adjust.

### Thread limiting (important!)

⚠️ **`transcodecpuWorkers` controls how many concurrent FFmpeg processes run,
but libx265 defaults to using ALL available CPU threads per process.** With 4
workers on a 16-core machine, that's 4 × 16 = 64 threads competing for 16
cores, causing massive oversubscription and system-wide slowdown.

**Fix 1 — Docker CPU cap (compose.starr.yml):**

```yaml
# compose.starr.yml → tdarr (top-level service key, not under environment)
cpus: 12    # hard-cap container to 12 cores, leaving 4 for the OS/other services
```

This is already applied in compose.starr.yml.

**Fix 2 — Per-encoder thread limit (Tdarr flow):**

Add `pools=4` to the `-x265-params` string in each Custom Arguments node of
your transcode flow. This tells x265 to use only ~4 threads per encode instead
of auto-detecting all cores.

- **HDR branch (Node 6a):** Change `outputArguments` to:
  ```
  -x265-params hdr-opt=1:repeat-headers=1:pools=4 -color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc -pix_fmt yuv420p10le
  ```
- **SDR branch:** Add a Custom Arguments node after Node 5b with:
  ```
  -x265-params pools=4
  ```

With `pools=4`, each worker uses ~4 threads → 4 workers × 4 threads = 16
threads total = full core utilization without oversubscription.

### Optional: add `starr` network

Tdarr is on the `proxy` network. Sonarr and Radarr are on both `proxy` and
`starr`. Since they share `proxy`, Tdarr can already reach them by container
hostname (`http://sonarr:8989`, `http://radarr:7878`). You can optionally
add the `starr` network to Tdarr for consistency:

```yaml
# compose.starr.yml → tdarr → networks (optional)
networks:
  - proxy
  - starr
```

### Transcode cache location

Currently mapped to `/tmp/tdarr_transcode_cache:/temp` which may be tmpfs
(RAM). Each encode can use 2–8 GB of temp space. If your system has limited
RAM, consider mapping to a disk path:

```yaml
# Option A: Keep RAM-based (fast, needs sufficient RAM)
- /tmp/tdarr_transcode_cache:/temp

# Option B: Use disk (slower but safer for large files)
- ${DATA}/tdarr/cache:/temp
```

### Apply changes

```bash
cd ~/homeserver/docker
docker compose -f compose.starr.yml up -d tdarr
```

---

## 4. Tdarr API Reference

Tdarr does **not** expose RESTful endpoints like `/api/v2/libraries`. Instead
it uses a **generic CRUDDB endpoint** for all data operations.

### No port mapping — use `docker exec`

Tdarr has no `ports:` mapping in the compose file — it's only accessible via
the NPM reverse proxy on the `proxy` network. For API calls from the host,
run curl inside the container:

```bash
docker exec tdarr curl -s http://localhost:8265/api/v2/...
```

`curl` is available inside the Tdarr container.

### Auth header

All API calls require the API key header:

```
-H "x-api-key: YOUR_TDARR_API_KEY"
```

The key is set via `${TDARR_API_KEY}` in the compose environment. Find the
value in your `.env` file.

### CRUDDB endpoint

```
POST http://localhost:8265/api/v2/cruddb
Content-Type: application/json
```

Body format:

```json
{
  "data": {
    "collection": "CollectionName",
    "mode": "getAll | getById | insert | update | removeOne",
    "docID": "unique-id",
    "obj": { "...document fields..." }
  }
}
```

#### Collections

| Collection | Purpose |
|-----------|---------|
| `LibrarySettingsJSONDB` | Library definitions (folder, variables, flow assignment) |
| `FlowsJSONDB` | Transcode flow definitions |
| `SettingsGlobalJSONDB` | Global Tdarr settings |
| `NodeJSONDB` | Worker node configuration |
| `VariablesJSONDB` | Global variables |
| `StatisticsJSONDB` | Processing statistics |

#### Additional endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/status` | `GET` | Server status |
| `/api/v2/stats/get-pies` | `POST` | Library statistics |

### Shell alias (optional)

```bash
# Add to .bashrc for convenience
tdarr-api() {
  docker exec tdarr curl -s \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_TDARR_API_KEY" \
    "$@"
}
```

---

## 5. Step-by-Step Configuration

### Step 1: Verify connectivity

```bash
docker exec tdarr curl -s \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/status | python3 -m json.tool
```

If this returns a JSON status object, the API is reachable.

### Step 2: Create TV libraries

> **Important:** Libraries must be created via the **Tdarr web UI**, not the
> CRUDDB API. The UI populates ~40+ required internal fields (schedule array,
> decisionMaker, containerFilter, watcher config, etc.) that the API does not
> auto-generate. Creating libraries via API with only a handful of fields
> causes fatal crashes when Tdarr tries to scan.

#### Delete broken API-created libraries (if any)

If you previously created libraries via the API and Tdarr is crashing, delete
them first:

```bash
for id in lib-tv-shows lib-anime-tv lib-indian-tv; do
  docker exec tdarr curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "x-api-key: YOUR_TDARR_API_KEY" \
    http://localhost:8265/api/v2/cruddb \
    -d "{\"data\":{\"collection\":\"LibrarySettingsJSONDB\",\"mode\":\"removeOne\",\"docID\":\"$id\"}}"
  echo " -> deleted $id"
done
```

After deleting, restart the Tdarr container to clear the crashed state:

```bash
docker restart tdarr
```

#### Create libraries via the UI

Open the Tdarr web UI → **Libraries** → **Library+** (top-left). Create each
library with these settings:

| Library | Source Folder (container path) |
|---------|-------------------------------|
| **TV Shows** | `/data/media/tv` |
| **Anime TV** | `/data/media/anime/tv` |
| **Indian TV** | `/data/media/indian/tv` |

For each library, configure:

1. **Source** tab → set the folder path from the table above
2. **Transcode Options** tab:
   - Enable **Process Library** and **Process Transcodes**
   - Set **Container** to `.mkv`
   - Set **Output Folder** to `.` (same as source — in-place)
3. **Scan** tab:
   - Enable **Folder Watching** if you want auto-detection of new files
   - Set scan interval as desired (e.g. 6 hours)

#### Verify libraries were created

```bash
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/cruddb \
  -d '{
    "data": {
      "collection": "LibrarySettingsJSONDB",
      "mode": "getAll"
    }
  }' | python3 -m json.tool
```

Note the `_id` for each library — Tdarr auto-generates short alphanumeric IDs
(e.g. `a7j-e2VqO`). Use these IDs in subsequent API commands.

### Step 3: Set library variables

Library variables allow the transcode flow to use different CRF values per
library via Handlebars templating (`{{{args.userVariables.library.xxx}}}`).

Variables can be set either via the **UI** or **API**:

- **UI:** Libraries → select library → **Variables** section → add key-value pairs
- **API:** Use the CRUDDB update commands below (replace `LIBRARY_ID` with the
  auto-generated `_id` from Step 2)

#### TV Shows — CRF 18

```bash
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/cruddb \
  -d '{
    "data": {
      "collection": "LibrarySettingsJSONDB",
      "mode": "update",
      "docID": "LIBRARY_ID",
      "obj": {
        "userVariables": {
          "crf": "18",
          "preset": "slow"
        }
      }
    }
  }'
```

#### Anime TV — CRF 18

Same command, replace `LIBRARY_ID` with the Anime TV library's `_id` and use
`"crf": "18"`.

#### Indian TV — CRF 20

Same command, replace `LIBRARY_ID` with the Indian TV library's `_id` and use
`"crf": "20"`.

### Step 4: Create the transcode flow

Tdarr flows use a **builder pattern** for ffmpeg commands — not a single
monolithic "Run FFmpeg Command" plugin. The flow editor is a visual graph in
the web UI. Below are the exact plugin names, input values, and connections.

> **Why document UI steps?** The flow JSON structure is undocumented and
> version-dependent. Building the flow once in the UI is more reliable than
> trying to POST flow JSON. You only need to do this once.

#### Flow: "HEVC x265 CPU Transcode"

Open the Tdarr web UI → **Flows** → **+ New Flow** → name it
`HEVC x265 CPU Transcode`.

Build the following plugin chain. Each numbered item is a node in the flow
editor. Connect them in order (Output 1 → next node's input, unless stated
otherwise).

---

**Node 1 — Check Video Codec (skip already HEVC)**

| Field | Value |
|-------|-------|
| Plugin | `video/checkVideoCodec` |
| `codec` (dropdown) | `hevc` |

- **Output 1** (file HAS hevc) → connect to a **Cancel Flow** node (skip)
- **Output 2** (file does NOT have hevc) → connect to Node 2

---

**Node 2 — Check File Size (skip tiny files)**

| Field | Value |
|-------|-------|
| Plugin | `file/checkFileSize` |
| `unit` | `MB` |
| `greaterThan` | `100` |
| `lessThan` | `100000` |

- **Output 1** (in range) → connect to Node 3
- **Output 2** (out of range, i.e. < 100 MB) → connect to Cancel Flow

---

**Node 3 — Check HDR**

| Field | Value |
|-------|-------|
| Plugin | `video/checkHdr` |
| *(no inputs)* | |

- **Output 1** (is HDR) → connect to Node 4a (HDR branch)
- **Output 2** (is not HDR) → connect to Node 4b (SDR branch)

---

**Node 4a — FFmpeg Command Start (HDR branch)**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandStart` |

→ connect to Node 5a

---

**Node 4b — FFmpeg Command Start (SDR branch)**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandStart` |

→ connect to Node 5b

---

**Node 5a — Set Video Encoder (HDR)**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandSetVideoEncoder` |
| `outputCodec` | `hevc` |
| `ffmpegPresetEnabled` | `true` |
| `ffmpegPreset` | `slow` |
| `ffmpegQualityEnabled` | `true` |
| `ffmpegQuality` | `{{{args.userVariables.library.crf}}}` |
| `hardwareEncoding` | `false` |
| `forceEncoding` | `false` (skip already-HEVC) |

→ connect to Node 6a

---

**Node 5b — Set Video Encoder (SDR)**

*(Identical to 5a — same settings. CPU encoding uses CRF automatically when
`hardwareEncoding` is false.)*

→ connect to Node 6b

---

**Node 6b — Custom Arguments (SDR thread limiting)**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandCustomArguments` |
| `inputArguments` | *(leave empty)* |
| `outputArguments` | `-x265-params pools=4` |

→ connect to Node 7 (Set Container)

---

**Node 6a — Custom Arguments (HDR metadata preservation)**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandCustomArguments` |
| `inputArguments` | *(leave empty)* |
| `outputArguments` | `-x265-params hdr-opt=1:repeat-headers=1:pools=4 -color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc -pix_fmt yuv420p10le` |

→ connect to Node 7 (Set Container)

---

**Node 7 — Set Container**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandSetContainer` |
| `container` | `.mkv` |

Both the HDR and SDR branches converge here.

→ connect to Node 8

---

**Node 8 — Execute FFmpeg**

| Field | Value |
|-------|-------|
| Plugin | `ffmpegCommand/ffmpegCommandExecute` |

→ connect to Node 9

---

**Node 9 — Replace Original File**

| Field | Value |
|-------|-------|
| Plugin | `file/replaceOriginalFile` |

→ connect to Node 10

---

**Node 10 — Notify Sonarr**

| Field | Value |
|-------|-------|
| Plugin | `tools/notifyRadarrOrSonarr` |
| `arr` | `sonarr` |
| `arr_api_key` | *(your Sonarr API key — Settings → General)* |
| `arr_host` | `http://sonarr:8989` |

- **Output 1** (notified successfully) → end
- **Output 2** (not found) → end (non-fatal — file still transcoded)

---

#### HDR handling — what's preserved and what's lost

| HDR format | Preserved through libx265? | Notes |
|-----------|--------------------------|-------|
| **HDR10** (static metadata) | ✅ Yes | The `checkHdr` branch adds the required x265-params and color flags |
| **HDR10+** (dynamic metadata) | ❌ No | Dynamic metadata is lost during re-encode — degrades to HDR10 |
| **Dolby Vision** | ❌ No | DV metadata cannot be preserved through libx265. Content degrades to base HDR10 layer or SDR |

If you want to **skip Dolby Vision content entirely** instead of losing DV
metadata, add a `video/checkVideoCodec` node checking for DV profile headers
before the transcode, or use `ffmpegCommand/ffmpegCommandCustomArguments` to
detect DV in the stream and route to Cancel Flow.

> **Practical note:** Most TV shows are SDR or HDR10. Dolby Vision TV content
> is relatively rare outside streaming originals, which you typically wouldn't
> have as files anyway.

### Step 5: Assign flows to libraries

In the Tdarr web UI → **Libraries** → select each library → **Transcode
Options** → set the **Flow** dropdown to `HEVC x265 CPU Transcode`.

Alternatively via API — first get the flow ID:

```bash
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/cruddb \
  -d '{
    "data": {
      "collection": "FlowsJSONDB",
      "mode": "getAll"
    }
  }' | python3 -m json.tool
```

Then assign to each library. Replace `FLOW_ID` with the flow `_id` from above,
and `LIBRARY_ID` with each library's auto-generated `_id` from Step 2:

```bash
# Repeat for each library ID
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/cruddb \
  -d '{
    "data": {
      "collection": "LibrarySettingsJSONDB",
      "mode": "update",
      "docID": "LIBRARY_ID",
      "obj": { "flow": "FLOW_ID" }
    }
  }'
```

### Step 6: Sonarr integration

The flow's `notifyRadarrOrSonarr` plugin handles the **Tdarr → Sonarr**
direction — it tells Sonarr that a file was replaced so Sonarr can update its
database. The plugin uses IMDB ID or filename parsing to find the series in
Sonarr and triggers a refresh command.

For the **Sonarr → Tdarr** direction (new downloads), rely on Tdarr's folder
watcher (`folderWatch: true` in the library config). Tdarr will pick up new
files automatically.

> **Sonarr API key:** Sonarr → Settings → General → Security → API Key
>
> **Sonarr host from Tdarr:** `http://sonarr:8989` (shared `proxy` network)

---

## 6. Movie Libraries (Future)

Follow the exact same pattern as TV libraries:

### Create movie libraries

Create each library via the **Tdarr web UI** (Libraries → Library+):

| Library | Source Folder (container path) | CRF |
|---------|-------------------------------|-----|
| **Movies** | `/data/media/movies` | 20 |
| **Anime Movies** | `/data/media/anime/movies` | 18 |
| **Indian Movies** | `/data/media/indian/movies` | 20 |

After creating each library in the UI, set variables via API (replace
`LIBRARY_ID` with the auto-generated `_id`):

```bash
# Example for Movies — CRF 20
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/cruddb \
  -d '{
    "data": {
      "collection": "LibrarySettingsJSONDB",
      "mode": "update",
      "docID": "LIBRARY_ID",
      "obj": {
        "userVariables": {
          "crf": "20",
          "preset": "slow"
        }
      }
    }
  }'
```

Or set the variables directly in the UI: Libraries → select library →
**Variables** section → add `crf` and `preset` keys.

### Create a movie transcode flow

Clone the TV flow in the UI and change only the notification node:

| Field | Change |
|-------|--------|
| `arr` | `radarr` (instead of `sonarr`) |
| `arr_api_key` | Your Radarr API key |
| `arr_host` | `http://radarr:7878` |

Then assign this flow to all three movie libraries.

---

## 7. FFmpeg Command Reference

These are the actual ffmpeg commands that Tdarr builds and executes. Useful
for testing outside Tdarr via `docker exec`.

### SDR content

```bash
docker exec tdarr ffmpeg \
  -i "/data/media/tv/Some Show/Season 01/episode.mkv" \
  -map 0 \
  -c:v libx265 -crf 20 -preset slow \
  -c:a copy -c:s copy \
  -max_muxing_queue_size 9999 \
  "/temp/test_sdr_output.mkv"
```

### HDR10 content

```bash
docker exec tdarr ffmpeg \
  -i "/data/media/tv/Some HDR Show/Season 01/episode.mkv" \
  -map 0 \
  -c:v libx265 -crf 20 -preset slow \
  -x265-params hdr-opt=1:repeat-headers=1 \
  -color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc \
  -pix_fmt yuv420p10le \
  -c:a copy -c:s copy \
  -max_muxing_queue_size 9999 \
  "/temp/test_hdr_output.mkv"
```

### Anime (lower CRF)

```bash
docker exec tdarr ffmpeg \
  -i "/data/media/anime/tv/Some Anime/Season 01/episode.mkv" \
  -map 0 \
  -c:v libx265 -crf 18 -preset slow \
  -c:a copy -c:s copy \
  -max_muxing_queue_size 9999 \
  "/temp/test_anime_output.mkv"
```

### Testing workflow

```bash
# 1. Pick a large x264 episode and transcode
docker exec tdarr ffmpeg \
  -i "/data/media/tv/Show Name/Season 01/S01E01.mkv" \
  -map 0 -c:v libx265 -crf 20 -preset slow \
  -c:a copy -c:s copy -max_muxing_queue_size 9999 \
  "/temp/test_output.mkv"

# 2. Compare file sizes
docker exec tdarr ls -lh "/data/media/tv/Show Name/Season 01/S01E01.mkv"
docker exec tdarr ls -lh "/temp/test_output.mkv"

# 3. Check the output is valid
docker exec tdarr ffprobe -hide_banner "/temp/test_output.mkv"

# 4. Clean up test file
docker exec tdarr rm "/temp/test_output.mkv"
```

Play the test output in Plex/Jellyfin to verify quality before enabling bulk
processing.

---

## 8. Encoding Settings & Quality

### Video settings per library

| Setting | TV Shows | Anime TV | Indian TV | Movies | Anime Movies |
|---------|----------|----------|-----------|--------|-------------|
| Encoder | `libx265` | `libx265` | `libx265` | `libx265` | `libx265` |
| CRF | **18** | **18** | **20** | **20** | **18** |
| Preset | `slow` | `slow` | `slow` | `slow` | `slow` |
| Container | `.mkv` | `.mkv` | `.mkv` | `.mkv` | `.mkv` |

TV Shows and Anime share CRF 18 — the TV library contains mixed content
including cartoons (Looney Toons, Kim Possible, etc.) that are vulnerable to
the same flat-color banding artifacts as anime. CRF 18 is safer for all
content at a modest ~15–20% size increase over CRF 20. Indian TV stays at
CRF 20 since it's primarily live-action.

### Audio & subtitles

- **Audio:** Copy all streams (`-c:a copy`) — never re-encode
- **Subtitles:** Copy all streams (`-c:s copy`)
- **Chapters & metadata:** Preserved via `-map 0`

### Skip conditions

Files are skipped (not re-encoded) when:

- Already HEVC/H.265 (`forceEncoding: false` in the encoder plugin)
- Below 100 MB (likely already compressed or bonus content)
- The flow's check-codec node catches HEVC before the builder starts

### CRF tuning guide

| CRF | Quality | Use case |
|-----|---------|----------|
| 16 | Near-lossless | Archival, reference quality |
| **18** | **Excellent** | **TV Shows, anime, cartoons — recommended** |
| 20 | Very good | Indian TV, general movies |
| 22 | Good | Bulk compression, less critical content |
| 24 | Acceptable | Maximum space savings, noticeable quality loss |

Lower CRF = higher quality = larger files. Each ±2 CRF roughly doubles/halves
the bitrate.

### Expected space savings

| Source | Typical savings |
|--------|----------------|
| x264 1080p → HEVC CRF 20 | 40–55 % smaller |
| x264 720p → HEVC CRF 20 | 35–50 % smaller |
| x264 4K → HEVC CRF 20 | 50–65 % smaller |

A 10 TB x264 library typically compresses to 4.5–6 TB in HEVC.

---

## 9. Monitoring & Plex/Jellyfin Notes

### Tdarr dashboard

The web UI shows real-time progress — files queued, processing, completed, and
space saved. Access it via your NPM reverse proxy. This is the easiest way to
monitor even when you configure everything via API.

### Processing order

Libraries use `sizeDesc` — largest files first. This maximizes early space
savings since bigger x264 files have the most room for compression.

### Library statistics via API

```bash
docker exec tdarr curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_TDARR_API_KEY" \
  http://localhost:8265/api/v2/stats/get-pies \
  -d '{}' | python3 -m json.tool
```

### Plex / Jellyfin behavior

Both point at the same media files. When Tdarr replaces an original with the
HEVC version:

- **Plex:** Automatically detects the change on next scan (or when Sonarr
  triggers a refresh via the notify plugin). May need to re-scan the library
  if thumbnails look stale.
- **Jellyfin:** Detects changes via its scheduled library scan. You can also
  add a webhook or flow step to hit Jellyfin's `/Library/Refresh` endpoint.
- **Direct play:** HEVC direct plays on virtually all modern clients (Roku,
  Apple TV, Android TV, Fire TV, Samsung/LG smart TVs 2016+, web browsers
  with HEVC support). No transcoding needed = no server load during playback.
