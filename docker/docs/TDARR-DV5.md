# Dolby Vision Profile 5 compatibility flow

This flow creates an Apple TV-compatible SDR copy **without replacing the
original movie**. It complements the Recyclarr penalty for DV-only WEB
releases; download scoring cannot inspect the actual video metadata.

## Checked-in implementation

- `docker/tdarr/dv5-sidecar.cjs`: worker-side detection, conversion and validation.
- `docker/tdarr/install-flow.cjs`: idempotent, authenticated Tdarr API installer.
- `docker/scripts/install-tdarr-dv5-flow.sh`: deploys both into the persistent
  `/app/server/Tdarr/Custom` directory without restarting Tdarr.

On the server, after the commits are deployed:

```bash
bash /srv/homeserver/docker/scripts/install-tdarr-dv5-flow.sh --apply
```

The installer requires the existing single colocated node to be idle. It
reads the API key inside the container, never writes it into the flow, and
uses `Community/customFunction` to load the versioned worker module.
Re-running it updates only its own flow; it preserves an existing movie
library's settings. Backups live under `Custom/backups`.

Flow ID: `homeserver-dv5-sidecar`.
Library ID: `homeserver-dv5-movies`.

**A newly installed library is disabled**, with no folder watcher, startup
scan, scheduled scan or processing enabled. Installation does not enqueue
the movie collection. Test a single file before deliberately enabling a
backlog.

## Processing contract

Only HEVC with a Dolby Vision configuration record reporting `dv_profile=5`
and `dv_bl_signal_compatibility_id=0` is eligible. Other files exit normally,
as do generated versions. The existing TV compression flow is not changed:
its libraries skip HEVC before the flow runs, and its replacement/notification
steps are not appropriate for a movie compatibility sidecar.

The source remains the working file returned to Tdarr. A successful sidecar
job therefore normally appears as **Not required**, not a replacement
transcode. Check the job's explicit sidecar result and the generated file.
There is no `replaceOriginalFile` node.

The output is H.264 SDR, at most 1920x1080 without upscaling, with
Dolby-Vision-aware CUDA tone mapping and BT.709 color tags. Bitrate is bounded
to provide headroom under the Apple TV's 20 Mbps setting. Compatible audio
is copied; unsupported audio is converted. Text subtitles use MP4
`mov_text` with millisecond timestamps to preserve long gaps between forced
cues. Unsupported subtitle formats fail rather than disappearing silently.
The worker deliberately uses `/usr/lib/jellyfin-ffmpeg/ffmpeg` and its sibling
`ffprobe`, not Tdarr's default `tdarr-ffmpeg` wrapper.

Outputs live below the movie's **`Plex Versions/Homeserver SDR/`** directory.
Radarr excludes `Plex Versions` from ordinary imports, so the generated copy
does not compete with its tracked original. Plex can scan the copy as another
version of the movie. This is not a Plex Optimizer job; do not configure
Optimizer cleanup to own this directory.

The module serializes its GPU work, checks available space, waits for stable
source files by rejecting recently modified inputs, and validates the result
before publishing it. It never overwrites an unrecognized existing file.
Source fingerprints and ownership records make repeated processing a no-op
only when the generated version is still valid. A changed source or conflicting
output requires deliberate review rather than silent replacement.
Run one compatibility job at a time: another worker encountering the GPU
lock fails explicitly and must be retried after the owner finishes. If a
worker is forcibly killed, confirm no compatibility encode remains before
removing a stale `Custom/dv5-sidecar.lock` directory.

## API rollout

Use `POST /api/v2/cruddb` with an `x-api-key` header. Read back every write:
HTTP 200 alone does not prove a database mutation succeeded.

For a pilot, create a separate library from the installed Tdarr defaults,
with the flow above, a single movie folder, no watchers, and only transcode
processing enabled. Then enqueue **one exact original file**:

```json
{
  "data": {
    "scanConfig": {
      "dbID": "YOUR_PILOT_LIBRARY_ID",
      "mode": "scanFolderWatcher",
      "arrayOrPath": ["/data/media/movies/Movie (Year)/original.mkv"]
    }
  }
}
```

Send this to `POST /api/v2/scan-files`. `scan-individual-file` only probes
metadata; it does not enqueue a worker job. Do not use `scanFresh` for a
single-file trial.

Inspect the file through `FileJSONDB` and its reports through
`list-footprintId-reports` / `job-reports/{jobId}`. Disable the pilot after
the run. Verify source size/mtime, output streams and seeking, Plex's actual
version selection at the intended quality limit, and Radarr's tracked
`movieFileId`. Before broad rollout, account for extra disk use and GPU
contention with Plex/Jellyfin. Originals remain in place, so this increases
storage rather than saving it.

## Local checks

```bash
node --test docker/tdarr/*.test.cjs
bash -n docker/scripts/install-tdarr-dv5-flow.sh
```
