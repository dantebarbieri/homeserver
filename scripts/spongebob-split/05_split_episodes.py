#!/usr/bin/env python3
"""Phase 4: split combined-block files into per-episode files using ffmpeg
stream-copy. Reads timecodes_s{N}.csv and writes outputs to a sibling
'Season 0N - split/' directory.

Per-row ffmpeg invocation:
    ffmpeg -y -ss <t_start_cut> -to <t_end_cut> -i <input> \
        -map 0 -map_chapters -1 -c copy -c:s srt \
        -avoid_negative_ts make_zero \
        -disposition:a 0 -disposition:a:0 default \
        -disposition:s 0 \
        <out>

Key details:
  * `-ss` placed BEFORE `-i` -> fast keyframe seek; works correctly with
    `-c copy` because t_start_cut was pre-snapped to a keyframe in
    Phase 3.
  * `-map 0 -c copy` keeps video, all audio, and all subtitle streams.
  * `-avoid_negative_ts make_zero` rewrites timestamps so the output
    starts at 0.
  * `-c:s srt` re-muxes SubRip so cues spanning the cut boundary are
    clipped/shifted correctly. Subtitle stream-copy would preserve raw
    packet timestamps and produce dangling cues.
  * `-disposition:a 0` then `-disposition:a:0 default` makes the first
    audio track default (per ffprobe a:0 is always English EAC3, a:1
    is Romanian in these files).
  * `-disposition:s 0` clears any subtitle defaults.
  * `-map_chapters -1` drops source chapters; they are minimal and
    would have wrong timestamps after cutting.

Output naming (sanitized titles, Sonarr-style):
    SpongeBob SquarePants (1999) - S0XEYY - <Title>.mkv

Usage:
    python3 05_split_episodes.py [season] [--dry-run] [--force] [-j N]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import lib


@dataclass
class SplitJob:
    file_index: int
    season: int
    episode: int
    title: str
    src: Path
    dst: Path
    t_start_cut: float
    t_end_cut: float
    t_start_true: float
    t_end_true: float


def load_jobs(season: int) -> list[SplitJob]:
    path = lib.STATE_DIR / f"timecodes_s{season}.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    src_dir = lib.SHOW_DIR / f"Season {season:02d}"
    dst_dir = lib.SHOW_DIR / f"Season {season:02d} - split"
    dst_dir.mkdir(exist_ok=True)
    jobs: list[SplitJob] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            src = src_dir / row["file_name"]
            if not src.exists():
                print(f"!! missing source: {src}", file=sys.stderr)
                continue
            dst_name = lib.output_filename(
                int(row["season"]),
                int(row["episode"]),
                row["title"],
            )
            jobs.append(
                SplitJob(
                    file_index=int(row["file_index"]),
                    season=int(row["season"]),
                    episode=int(row["episode"]),
                    title=row["title"],
                    src=src,
                    dst=dst_dir / dst_name,
                    t_start_cut=float(row["t_start_cut_s"]),
                    t_end_cut=float(row["t_end_cut_s"]),
                    t_start_true=float(row["t_start_true_s"]),
                    t_end_true=float(row["t_end_true_s"]),
                )
            )
    return jobs


def build_ffmpeg_cmd(job: SplitJob) -> list[str]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-ss",
        lib.format_timecode(job.t_start_cut),
        "-i",
        str(job.src),
        # Use -t (duration) as an OUTPUT option. Input-side -ss + -to
        # was observed to silently ignore -to (output ran to EOF). The
        # output-side -t form is the canonical, reliable pattern.
        "-t",
        f"{job.t_end_cut - job.t_start_cut:.3f}",
        "-map",
        "0",
        "-map_chapters",
        "-1",
        "-c",
        "copy",
        # Re-mux SubRip so cues that span the cut boundary are clipped
        # / shifted correctly (subtitle stream-copy would preserve raw
        # packets and leak into negative or past-end timestamps).
        "-c:s",
        "srt",
        "-avoid_negative_ts",
        "make_zero",
        # Reset all audio default flags, then make English audio (a:0)
        # default. Per ffprobe, a:0 is always English EAC3 and a:1 is
        # Romanian.
        "-disposition:a",
        "0",
        "-disposition:a:0",
        "default",
        # Clear subtitle defaults so the player chooses based on user prefs.
        "-disposition:s",
        "0",
        # Tag the file with the canonical title.
        "-metadata",
        f"title={job.title}",
        str(job.dst),
    ]
    return cmd


def run_one(job: SplitJob, dry_run: bool, force: bool) -> tuple[SplitJob, str]:
    if job.dst.exists() and not force:
        return job, "skip (exists; use --force to overwrite)"
    if dry_run:
        cmd = build_ffmpeg_cmd(job)
        return job, "DRY-RUN " + " ".join(_shell_quote(a) for a in cmd)
    try:
        res = subprocess.run(
            build_ffmpeg_cmd(job),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return job, f"ERROR: {e.stderr.strip().splitlines()[-1] if e.stderr else e}"
    # Validate output duration is within tolerance.
    try:
        out_dur = lib.probe_duration(job.dst)
    except Exception as e:  # noqa: BLE001
        return job, f"ERROR validating: {e!r}"
    expected = job.t_end_cut - job.t_start_cut
    drift = abs(out_dur - expected)
    tag = "OK" if drift < 2.0 else f"WARN drift={drift:.2f}s"
    return job, f"{tag}  out_dur={out_dur:.1f}s  expected={expected:.1f}s"


def _shell_quote(s: str) -> str:
    if not s or any(c in s for c in ' "\'$`\\'):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", nargs="?", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "-j", "--jobs", type=int, default=2, help="parallel workers"
    )
    args = ap.parse_args()

    jobs = load_jobs(args.season)
    print(f"Loaded {len(jobs)} segments for Season {args.season}")
    if not jobs:
        return
    dst_dir = jobs[0].dst.parent
    print(f"Output dir: {dst_dir}")

    log_path = lib.STATE_DIR / f"split_s{args.season}.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"--- run jobs={args.jobs} dry={args.dry_run} force={args.force} ---\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futures = {
                ex.submit(run_one, j, args.dry_run, args.force): j
                for j in jobs
            }
            for fut in concurrent.futures.as_completed(futures):
                job, status = fut.result()
                line = (
                    f"[file-{job.file_index:02d}] "
                    f"S{job.season:02d}E{job.episode:02d} "
                    f"{job.title!r}  ->  {job.dst.name}  ::  {status}"
                )
                print(line)
                log.write(line + "\n")
                log.flush()


if __name__ == "__main__":
    main()
