#!/usr/bin/env bash
# transcode-dv-tapes.sh
# One-time conversion of the digitized MiniDV home videos (DV-in-MKV, Segu
# "Tape NNN" folders) to H.264/AAC MP4.
#
# Why: Plex loads its DV decoder from a downloaded codec pack, and the pack
# shipped for 1.43.x is broken ("could not find dv frame profile"), so every
# playback of these files fails to transcode. Re-downloading fetches identical
# bytes, and no fixed release exists, so the durable fix is to stop needing
# the dvvideo decoder at all: H.264+AAC direct-plays on every client.
#
# Decoding/encoding uses the jellyfin-finity image's ffmpeg, which decodes
# these files cleanly (verified 2026-07-24). Originals are never deleted.
#
# Usage (on the server):
#   ./transcode-dv-tapes.sh          # convert; leave originals in place
#   ./transcode-dv-tapes.sh --move   # after each verified conversion, move the
#                                    # original into $ORIGINALS_DIR so Plex
#                                    # doesn't show duplicates
#
# Environment overrides: SEGU_DIR, ORIGINALS_DIR, FFMPEG_IMAGE

set -euo pipefail

SEGU_DIR="${SEGU_DIR:-/data/shared/media/other/Segu}"
ORIGINALS_DIR="${ORIGINALS_DIR:-/data/shared/media/other/Segu-DV-originals}"
FFMPEG_IMAGE="${FFMPEG_IMAGE:-jellyfin-finity:latest}"
MOVE_ORIGINALS=0
[ "${1:-}" = "--move" ] && MOVE_ORIGINALS=1

FFMPEG_BIN=/usr/lib/jellyfin-ffmpeg/ffmpeg
FFPROBE_BIN=/usr/lib/jellyfin-ffmpeg/ffprobe

run_tool() { # <entrypoint> <args...> — run ffmpeg/ffprobe inside the image with $SEGU_DIR mounted at /work
    local tool="$1"; shift
    docker run --rm --entrypoint "$tool" --user "$(id -u):$(id -g)" \
        -v "$SEGU_DIR:/work" "$FFMPEG_IMAGE" "$@"
}

duration_of() { # <container path> -> whole seconds (empty on failure)
    run_tool "$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$1" | cut -d. -f1
}

codec_of() { # <container path> -> video codec name
    run_tool "$FFPROBE_BIN" -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$1"
}

converted=0 skipped=0 failed=0

while IFS= read -r -d '' src; do
    rel="${src#"$SEGU_DIR"/}"          # path relative to SEGU_DIR (== path under /work)
    out_rel="${rel%.mkv}.mp4"
    tmp_rel="${rel%.mkv}.part.mp4"

    if [ -f "$SEGU_DIR/$out_rel" ]; then
        echo "SKIP (already converted): $rel"
        if [ "$MOVE_ORIGINALS" -eq 1 ]; then
            dest_dir="$ORIGINALS_DIR/$(dirname "$rel")"
            mkdir -p "$dest_dir"
            mv "$src" "$dest_dir/"
            echo "  original moved to $dest_dir/"
        fi
        skipped=$((skipped + 1))
        continue
    fi

    if [ "$(codec_of "/work/$rel")" != "dvvideo" ]; then
        echo "SKIP (not DV): $rel"
        skipped=$((skipped + 1))
        continue
    fi

    echo "CONVERT: $rel"
    # NTSC DV is interlaced bottom-field-first; bwdif send_field yields 59.94p.
    # SAR 8:9 x 720x480 displays as 4:3 — scale to square-pixel 640x480.
    if ! run_tool "$FFMPEG_BIN" -nostdin -v error -y \
            -i "/work/$rel" \
            -vf "bwdif=mode=send_field:parity=bff:deint=all,scale=640:480,setsar=1" \
            -c:v libx264 -preset slow -crf 18 \
            -c:a aac -b:a 256k \
            -movflags +faststart \
            "/work/$tmp_rel"; then
        echo "FAIL (ffmpeg error): $rel"
        rm -f "$SEGU_DIR/$tmp_rel"
        failed=$((failed + 1))
        continue
    fi

    src_dur="$(duration_of "/work/$rel")"
    out_dur="$(duration_of "/work/$tmp_rel")"
    if [ -z "$src_dur" ] || [ -z "$out_dur" ] || [ "$((src_dur - out_dur))" -gt 2 ] || [ "$((out_dur - src_dur))" -gt 2 ]; then
        echo "FAIL (duration mismatch: src=${src_dur}s out=${out_dur}s): $rel"
        rm -f "$SEGU_DIR/$tmp_rel"
        failed=$((failed + 1))
        continue
    fi

    mv "$SEGU_DIR/$tmp_rel" "$SEGU_DIR/$out_rel"
    converted=$((converted + 1))

    if [ "$MOVE_ORIGINALS" -eq 1 ]; then
        dest_dir="$ORIGINALS_DIR/$(dirname "$rel")"
        mkdir -p "$dest_dir"
        mv "$src" "$dest_dir/"
        echo "  original moved to $dest_dir/"
    fi
done < <(find "$SEGU_DIR" -type f -name '*.mkv' -path '*/Tape *' -print0 | sort -z)

echo "----- Done: $converted converted, $skipped skipped, $failed failed -----"
[ "$failed" -eq 0 ]
