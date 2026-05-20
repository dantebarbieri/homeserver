#!/usr/bin/env python3
"""Phase 2: extract thumbnail strips for S1 files so the user can identify
which CSV block lives in each file.

Outputs one tiled JPEG per file under STATE_DIR/thumbs/s1/file-NN.jpg.
Each strip is a single row of 8 frames sampled at evenly-spaced timestamps
across the file's duration.

Also emits STATE_DIR/mapping_s1_template.csv pre-populated with the
"sequential" guess so the user only has to correct it.

Usage (inside `nix shell nixpkgs#ffmpeg nixpkgs#python3 -c bash`):

    python3 01_make_thumb_strips.py
"""

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

import lib

SEASON = 1
N_FRAMES = 8
THUMB_HEIGHT = 180  # pixels; total strip width = 8 * (THUMB_HEIGHT * 16/9)


def make_strip(input_file: Path, out_jpg: Path, duration: float) -> None:
    # Pick N evenly-spaced timestamps avoiding the very edges.
    step = duration / (N_FRAMES + 1)
    timestamps = [step * (i + 1) for i in range(N_FRAMES)]
    # Build select expression: pick the frame closest to each timestamp.
    # Simpler: extract one frame per timestamp, then tile with `montage`-like
    # ffmpeg hstack. We'll do it in a single command using -ss per input
    # and the hstack filter.
    inputs: list[str] = []
    for t in timestamps:
        inputs += ["-ss", f"{t:.3f}", "-i", str(input_file)]
    filter_parts = []
    for i in range(N_FRAMES):
        filter_parts.append(f"[{i}:v]scale=-2:{THUMB_HEIGHT}[v{i}]")
    hstack_inputs = "".join(f"[v{i}]" for i in range(N_FRAMES))
    filter_parts.append(f"{hstack_inputs}hstack=inputs={N_FRAMES}[out]")
    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-frames:v",
        "1",
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-q:v",
        "3",
        str(out_jpg),
        "-loglevel",
        "error",
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    state = lib.ensure_state_dir()
    thumb_dir = state / "thumbs" / f"s{SEASON}"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    files = lib.list_season_files(SEASON)
    print(f"Found {len(files)} files in Season {SEASON}")

    # Sequential mapping guess from CSV.
    rows = lib.load_old_csv()
    blocks = lib.group_into_blocks(rows)
    s_blocks = [b for b in blocks if b.season == SEASON]
    print(f"Found {len(s_blocks)} catalogued blocks in CSV")

    template_path = state / f"mapping_s{SEASON}_template.csv"
    with template_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file_index",
                "file_name",
                "duration_s",
                "guess_block_first_ep",
                "guess_block_last_ep",
                "guess_episodes",
                "guess_titles",
                "actual_episodes",
            ]
        )
        for i, path in enumerate(files):
            print(f"  [{i + 1}/{len(files)}] {path.name}")
            dur = lib.probe_duration(path)
            out = thumb_dir / f"file-{i + 1:02d}.jpg"
            make_strip(path, out, dur)
            if i < len(s_blocks):
                b = s_blocks[i]
                eps = ",".join(str(r.episode) for r in b.rows)
                titles = " + ".join(r.title for r in b.rows)
                w.writerow(
                    [
                        i + 1,
                        path.name,
                        f"{dur:.3f}",
                        b.first_episode,
                        b.last_episode,
                        eps,
                        titles,
                        eps,  # pre-fill with guess; user edits
                    ]
                )
            else:
                w.writerow(
                    [i + 1, path.name, f"{dur:.3f}", "", "", "", "", ""]
                )
    print(f"\nWrote {template_path}")
    print(f"Thumbnails in {thumb_dir}")
    print("\nNext steps:")
    print(
        "  1. SCP the thumbs to your laptop: "
        f"scp -r 'server:{thumb_dir}' ."
    )
    print(
        f"  2. Edit {template_path} - update 'actual_episodes' column "
        "(comma-separated episode numbers in order)"
    )
    print(
        f"  3. Rename to mapping_s{SEASON}.csv when done"
    )


if __name__ == "__main__":
    main()
