#!/usr/bin/env python3
"""Phase 2 (v3): extract many candidate title-card strips per file.

The user only needs to FIND the title cards; spurious strips are fine.
So we cast a very wide net and emit one strip per candidate boundary,
sourced from every cheap signal we have:

  * t = 0 (intro window for segment 1)
  * Every blackdetect interval (don't require silence overlap)
  * Every silencedetect interval (don't require black overlap)
  * Every chapter start from the container metadata
  * Old CSV boundaries, scaled by new_duration / old_block_duration
    when an old-block guess is available
  * Fixed fractions: 1/3, 1/2, 2/3 of duration

Candidates are deduped (within 5s) and dropped if outside (60s, dur-60s).

Each candidate -> one ~13-frame horizontal strip starting just after it.
All strips for a file are vstack'd into file-NN.jpg.

Usage:
  python3 02_make_titlecard_strips.py [season]
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import lib

DEFAULT_SEASON = 1

BLACK_MIN_DURATION = 0.20
BLACK_PIX_THRESHOLD = 0.10
SILENCE_MIN_DURATION = 0.40
SILENCE_DB = -40

POST_BOUNDARY_START = -1.0  # include the last frame before fade
POST_BOUNDARY_END = 14.0
FRAMES_PER_BOUNDARY = 12
THUMB_HEIGHT = 200

# Drop candidates this close to either edge (intro / credits).
EDGE_PAD = 45.0
DEDUPE_WINDOW = 5.0


@dataclass
class Interval:
    start: float
    end: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.start + self.end)


def _run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stderr + res.stdout


_BLACK_RE = re.compile(
    r"black_start:(?P<start>[\d.]+)\s+black_end:(?P<end>[\d.]+)"
)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<start>[-\d.]+)")
_SILENCE_END_RE = re.compile(
    r"silence_end:\s*(?P<end>[\d.]+)\s*\|\s*silence_duration:"
)


def detect_black(path: Path) -> list[Interval]:
    out = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            f"blackdetect=d={BLACK_MIN_DURATION}:pix_th={BLACK_PIX_THRESHOLD}",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    return [
        Interval(float(m["start"]), float(m["end"]))
        for m in _BLACK_RE.finditer(out)
    ]


def detect_silence(path: Path) -> list[Interval]:
    out = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_DURATION}",
            "-vn",
            "-f",
            "null",
            "-",
        ]
    )
    starts = [float(m["start"]) for m in _SILENCE_START_RE.finditer(out)]
    ends = [float(m["end"]) for m in _SILENCE_END_RE.finditer(out)]
    n = min(len(starts), len(ends))
    return [Interval(starts[i], ends[i]) for i in range(n)]


def detect_chapters(path: Path) -> list[float]:
    data = lib.ffprobe_json(["-show_chapters", str(path)])
    return [float(c["start_time"]) for c in data.get("chapters", [])]


def collect_candidates(
    path: Path,
    duration: float,
    csv_hints: list[float] | None,
) -> tuple[list[tuple[float, str]], dict]:
    """Return list of (timestamp, source_tag) candidates plus diagnostics."""
    blacks = detect_black(path)
    silences = detect_silence(path)
    chapters = detect_chapters(path)

    cands: list[tuple[float, str]] = []
    for b in blacks:
        cands.append((b.mid, f"black"))
    for s in silences:
        cands.append((s.mid, f"silence"))
    for c in chapters:
        cands.append((c, f"chapter"))
    for frac in (1 / 3, 1 / 2, 2 / 3):
        cands.append((duration * frac, f"frac{int(frac * 100)}"))
    if csv_hints:
        for h in csv_hints:
            cands.append((h, "csv"))

    # Edge filter.
    cands = [(t, tag) for (t, tag) in cands if EDGE_PAD <= t <= duration - EDGE_PAD]

    # Sort, dedupe within DEDUPE_WINDOW (keep earliest occurrence's
    # timestamp but record all overlapping sources).
    cands.sort(key=lambda x: x[0])
    merged: list[tuple[float, str]] = []
    for t, tag in cands:
        if merged and t - merged[-1][0] <= DEDUPE_WINDOW:
            prev_t, prev_tag = merged[-1]
            if tag not in prev_tag.split("+"):
                merged[-1] = (prev_t, prev_tag + "+" + tag)
        else:
            merged.append((t, tag))

    # Rule (post-S1 lesson): silence by itself is the most common false
    # positive. Drop any merged candidate whose only source is silence.
    merged = [(t, tag) for (t, tag) in merged if tag.split("+") != ["silence"]]

    diag = {
        "n_blacks": len(blacks),
        "n_silences": len(silences),
        "n_chapters": len(chapters),
        "n_csv": len(csv_hints) if csv_hints else 0,
        "n_candidates_raw": len(cands),
        "n_candidates_merged": len(merged),
    }
    return merged, diag


def extract_strip(
    path: Path, timestamps: list[float], out_jpg: Path
) -> None:
    inputs: list[str] = []
    for t in timestamps:
        inputs += ["-ss", f"{max(0.0, t):.3f}", "-i", str(path)]
    parts = []
    for i in range(len(timestamps)):
        parts.append(f"[{i}:v]scale=-2:{THUMB_HEIGHT}[v{i}]")
    stack_in = "".join(f"[v{i}]" for i in range(len(timestamps)))
    parts.append(f"{stack_in}hstack=inputs={len(timestamps)}[out]")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-frames:v",
            "1",
            "-filter_complex",
            ";".join(parts),
            "-map",
            "[out]",
            "-q:v",
            "3",
            str(out_jpg),
            "-loglevel",
            "error",
        ],
        check=True,
    )


def get_csv_hints_for_file_index(
    season: int, file_index: int, duration: float
) -> list[float] | None:
    """If the CSV's Nth block (1-indexed) has known boundaries, scale them
    by new_duration / old_block_duration_guess. We can't know the old
    block's total duration so we just use the raw CSV timecodes as-is --
    they were on similar-length WEBDL/PMTP files (~23min), so they're a
    decent guess."""
    rows = lib.load_old_csv()
    blocks = lib.group_into_blocks(rows)
    s_blocks = [b for b in blocks if b.season == season]
    if file_index < 1 or file_index > len(s_blocks):
        return None
    b = s_blocks[file_index - 1]
    hints: list[float] = []
    for r in b.rows:
        if r.t_start is not None and r.t_start > 0:
            hints.append(r.t_start)
        if r.t_end is not None:
            hints.append(r.t_end)
    return hints


def build_file_image(
    path: Path,
    season: int,
    file_index: int,
    duration: float,
    out_jpg: Path,
) -> dict:
    csv_hints = get_csv_hints_for_file_index(season, file_index, duration)
    candidates, diag = collect_candidates(path, duration, csv_hints)

    # Always prepend a file-start strip (covers segment 1's title card).
    work_dir = out_jpg.parent / f"file-{file_index:02d}-parts"
    work_dir.mkdir(exist_ok=True)
    for old in work_dir.glob("*.jpg"):
        old.unlink()
    strips: list[Path] = []

    start_ts = [28.0 + i * (50.0 / 11) for i in range(12)]  # 28s..78s
    start_ts = [t for t in start_ts if t < duration - 1]
    if start_ts:
        s0 = work_dir / "00-start.jpg"
        extract_strip(path, start_ts, s0)
        strips.append(s0)

    for i, (t, tag) in enumerate(candidates, start=1):
        ts_lo = t + POST_BOUNDARY_START
        ts_hi = min(t + POST_BOUNDARY_END, duration - 0.5)
        if ts_hi <= ts_lo:
            continue
        step = (ts_hi - ts_lo) / (FRAMES_PER_BOUNDARY - 1)
        ts = [ts_lo + j * step for j in range(FRAMES_PER_BOUNDARY)]
        safe_tag = tag.replace("+", "_")
        strip = work_dir / f"{i:02d}-{int(t):05d}s-{safe_tag}.jpg"
        try:
            extract_strip(path, ts, strip)
            strips.append(strip)
        except subprocess.CalledProcessError as e:
            print(f"    skip candidate at {t:.1f}s ({tag}): {e}")

    # Vstack all strips.
    if len(strips) == 1:
        import shutil as _sh
        _sh.copyfile(strips[0], out_jpg)
    elif len(strips) > 1:
        inputs: list[str] = []
        for s in strips:
            inputs += ["-i", str(s)]
        parts = [
            f"[{i}:v]scale=2400:-2[v{i}]" for i in range(len(strips))
        ]
        stack_in = "".join(f"[v{i}]" for i in range(len(strips)))
        parts.append(f"{stack_in}vstack=inputs={len(strips)}[out]")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-filter_complex",
                ";".join(parts),
                "-map",
                "[out]",
                "-q:v",
                "3",
                str(out_jpg),
                "-loglevel",
                "error",
            ],
            check=True,
        )

    diag["n_strips"] = len(strips)
    diag["candidates"] = candidates
    return diag


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEASON
    state = lib.ensure_state_dir()
    out_dir = state / "titlecards" / f"s{season}"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = lib.list_season_files(season)
    print(f"Found {len(files)} files in Season {season}\n")

    summary_lines: list[str] = []
    for i, path in enumerate(files, start=1):
        print(f"[{i}/{len(files)}] {path.name}")
        dur = lib.probe_duration(path)
        out_jpg = out_dir / f"file-{i:02d}.jpg"
        info = build_file_image(path, season, i, dur, out_jpg)
        cand_str = ", ".join(
            f"{int(t // 60)}:{int(t % 60):02d}[{tag}]"
            for t, tag in info["candidates"]
        )
        line = (
            f"  file-{i:02d}: dur={dur:.0f}s  "
            f"blk={info['n_blacks']} sil={info['n_silences']} "
            f"chp={info['n_chapters']} csv={info['n_csv']}  "
            f"strips={info['n_strips']}  candidates=[{cand_str}]"
        )
        print(line)
        summary_lines.append(line)

    summary_path = out_dir / "candidates.txt"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"\nWrote {summary_path}")
    print(f"Per-file images: {out_dir}/file-NN.jpg")


if __name__ == "__main__":
    main()
