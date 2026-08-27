#!/bin/bash

set -euo pipefail

container="${1:-plex}"

if [ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]; then
    echo "ERROR: Plex container '$container' is not running." >&2
    exit 1
fi

if ! output=$(
    docker exec -u plex "$container" sh -c '
        dd if=/dev/zero bs=98304 count=1 status=none |
            "/usr/lib/plexmediaserver/Plex Transcoder" \
                -hide_banner \
                -loglevel error \
                -init_hw_device cuda=plex:0 \
                -f rawvideo \
                -pixel_format yuv420p \
                -video_size 256x256 \
                -framerate 1 \
                -i pipe:0 \
                -frames:v 1 \
                -c:v h264_nvenc \
                -f null \
                /dev/null
    ' 2>&1
); then
    echo "ERROR: Plex CUDA/NVENC probe failed." >&2
    printf '%s\n' "$output" >&2
    exit 1
fi

echo "Plex CUDA/NVENC probe passed."
