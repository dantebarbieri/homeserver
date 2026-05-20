#!/usr/bin/env python3
"""Phase 3: re-derive precise segment boundaries on the new files.

For each row in mapping_s{N}.csv, look up the file's episode list and the
corresponding CSV rows. For each within-file boundary (between consecutive
segments), find the precise time via blackdetect+silencedetect in a tight
window around the CSV's seed, then snap to the nearest video keyframe
<= that time (so stream-copy cuts are clean).

Output: STATE_DIR/timecodes_s{N}.csv with columns:
    file_index, file_name, season, episode, title, seg_index,
    t_start_true, t_end_true,         # frame-accurate boundaries (seconds)
    t_start_cut,  t_end_cut,          # keyframe-snapped boundaries used by ffmpeg
    confidence,                       # "csv+black+silence", "csv+black", ...
    needs_review                      # True if any boundary used a fallback

Files marked SINGLE (or any file whose actual_episodes list cannot be
matched to a CSV block) are skipped with a warning.

Usage:
    python3 04_find_boundaries.py [season]
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import lib

DEFAULT_SEASON = 1

# Window around the CSV seed in which we look for the real boundary.
WINDOW = 25.0  # +/- seconds
BLACK_MIN_DURATION = 0.20
BLACK_PIX_THRESHOLD = 0.10
SILENCE_MIN_DURATION = 0.30
SILENCE_DB = -40

# How far the chosen "true" boundary may sit from the CSV seed before we
# flag it for review.
SEED_TRUST_WINDOW = 8.0
# If no signal at all is found, fall back to the seed itself but mark
# needs_review.
SINGLE_DURATION_MAX = 900


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


def detect_in_window(
    path: Path, t_lo: float, t_hi: float
) -> tuple[list[Interval], list[Interval]]:
    """Run blackdetect and silencedetect over a small window of `path`."""
    duration = t_hi - t_lo
    out = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{t_lo:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-vf",
            f"blackdetect=d={BLACK_MIN_DURATION}:pix_th={BLACK_PIX_THRESHOLD}",
            "-af",
            f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_DURATION}",
            "-f",
            "null",
            "-",
        ]
    )
    blacks = [
        Interval(t_lo + float(m["start"]), t_lo + float(m["end"]))
        for m in _BLACK_RE.finditer(out)
    ]
    starts = [t_lo + float(m["start"]) for m in _SILENCE_START_RE.finditer(out)]
    ends = [t_lo + float(m["end"]) for m in _SILENCE_END_RE.finditer(out)]
    n = min(len(starts), len(ends))
    silences = [Interval(starts[i], ends[i]) for i in range(n)]
    return blacks, silences


def find_boundary(
    path: Path, seed: float, duration: float
) -> tuple[float, str]:
    """Return (boundary_time, confidence_tag).

    Strategy:
      1. blackdetect & silencedetect within (seed-WINDOW, seed+WINDOW).
      2. Best = a black interval whose midpoint is closest to seed AND
         overlaps a silent interval. confidence = "csv+black+silence".
      3. Else best = closest black midpoint. confidence = "csv+black".
      4. Else best = closest silence midpoint. confidence = "csv+silence".
      5. Else: return the seed itself. confidence = "csv-only" (review!).
    """
    t_lo = max(0.0, seed - WINDOW)
    t_hi = min(duration, seed + WINDOW)
    blacks, silences = detect_in_window(path, t_lo, t_hi)

    def overlaps_any_silence(b: Interval) -> bool:
        return any(b.start <= s.end and s.start <= b.end for s in silences)

    # Candidate 1: black AND silence.
    bs = [b for b in blacks if overlaps_any_silence(b)]
    if bs:
        best = min(bs, key=lambda b: abs(b.mid - seed))
        return best.mid, "csv+black+silence"

    # Candidate 2: black alone.
    if blacks:
        best = min(blacks, key=lambda b: abs(b.mid - seed))
        return best.mid, "csv+black"

    # Candidate 3: silence alone.
    if silences:
        best = min(silences, key=lambda s: abs(s.mid - seed))
        return best.mid, "csv+silence"

    # No signal at all -- use seed.
    return seed, "csv-only"


def keyframes_in_range(
    path: Path, t_lo: float, t_hi: float
) -> list[float]:
    """List video keyframe PTS times (in seconds) within [t_lo, t_hi]."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-skip_frame",
        "nokey",
        "-show_entries",
        "frame=pts_time",
        "-read_intervals",
        f"{max(0.0, t_lo):.3f}%{t_hi:.3f}",
        "-of",
        "json",
        str(path),
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(res.stdout or "{}")
    return [
        float(f["pts_time"])
        for f in data.get("frames", [])
        if "pts_time" in f
    ]


def snap_to_keyframe_le(
    path: Path, t: float, duration: float
) -> float:
    """Return the largest keyframe time <= t. Falls back to t if none found
    (which is unusual but safe for stream-copy because ffmpeg will internally
    snap)."""
    # Search a generous window before t; SpongeBob WEBDL GOPs are usually
    # <= ~10s, but we widen to 20s to be safe.
    t_lo = max(0.0, t - 20.0)
    t_hi = min(duration, t + 0.5)
    kfs = keyframes_in_range(path, t_lo, t_hi)
    kfs = [k for k in kfs if k <= t + 0.01]
    if not kfs:
        return t
    return max(kfs)


@dataclass
class Segment:
    file_index: int
    file_name: str
    season: int
    episode: int
    title: str
    seg_index: int  # 1-based within the file
    t_start_true: float
    t_end_true: float
    t_start_cut: float
    t_end_cut: float
    confidence_start: str
    confidence_end: str
    needs_review: bool


def parse_episode_list(s: str) -> list[int]:
    s = (s or "").strip()
    if not s:
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def load_mapping(season: int) -> list[dict]:
    path = lib.STATE_DIR / f"mapping_s{season}.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def csv_rows_by_season_episode(season: int) -> dict[int, lib.OldRow]:
    rows = lib.load_old_csv()
    return {r.episode: r for r in rows if r.season == season}


def process_file(
    mapping_row: dict, csv_by_ep: dict[int, lib.OldRow], duration_cache: dict
) -> list[Segment]:
    file_index = int(mapping_row["file_index"])
    file_name = mapping_row["file_name"]
    eps = parse_episode_list(mapping_row.get("actual_episodes", ""))
    if not eps:
        print(f"  file-{file_index:02d}: SKIP (no actual_episodes)")
        return []

    path = lib.SHOW_DIR / mapping_row["file_name"].split("/")[0]
    # The mapping CSV stores just the filename; we need to find which
    # Season XX directory holds it.
    season = csv_by_ep[eps[0]].season
    season_dir = lib.SHOW_DIR / f"Season {season:02d}"
    full_path = season_dir / file_name

    if file_index in duration_cache:
        dur = duration_cache[file_index]
    else:
        dur = lib.probe_duration(full_path)
        duration_cache[file_index] = dur

    if dur <= SINGLE_DURATION_MAX:
        print(
            f"  file-{file_index:02d}: SKIP (single-episode file, "
            f"dur={dur:.0f}s; we'll re-derive from a combined file)"
        )
        return []

    n = len(eps)
    # Build seed boundaries between consecutive segments using the CSV.
    # CSV row for episode e has t_end (end of e within its old block) =
    # start of e+1. We use the e_n.t_end as the seed for the boundary
    # between segments n and n+1.
    seeds: list[float] = []
    for i in range(n - 1):
        ep_here = eps[i]
        row = csv_by_ep.get(ep_here)
        if row is None or row.t_end is None:
            # Fall back to fractional position.
            seeds.append(dur * (i + 1) / n)
        else:
            seeds.append(row.t_end)

    # Resolve real boundaries.
    boundaries_true: list[float] = []  # length n-1
    confidences: list[str] = []
    for seed in seeds:
        t, conf = find_boundary(full_path, seed, dur)
        boundaries_true.append(t)
        confidences.append(conf)

    # Build per-segment intervals.
    seg_starts_true = [0.0] + boundaries_true
    seg_ends_true = boundaries_true + [dur]
    seg_starts_cut: list[float] = []
    seg_ends_cut: list[float] = []
    for s, e in zip(seg_starts_true, seg_ends_true):
        # Cut must snap to a keyframe <= start (so video begins on a
        # decoder-ready frame). End can simply be true end -- ffmpeg
        # with -c copy will copy up to the last keyframe <= -to.
        if s <= 0.001:
            seg_starts_cut.append(0.0)
        else:
            seg_starts_cut.append(snap_to_keyframe_le(full_path, s, dur))
        seg_ends_cut.append(e)

    out: list[Segment] = []
    for i, ep in enumerate(eps):
        row = csv_by_ep.get(ep)
        title = row.title if row else f"S{season:02d}E{ep:02d}"
        conf_start = "file-start" if i == 0 else confidences[i - 1]
        conf_end = "file-end" if i == n - 1 else confidences[i]
        seed_drift = 0.0
        if i > 0:
            seed_drift = abs(boundaries_true[i - 1] - seeds[i - 1])
        if i < n - 1:
            seed_drift = max(
                seed_drift, abs(boundaries_true[i] - seeds[i])
            )
        needs_review = (
            seed_drift > SEED_TRUST_WINDOW
            or "csv-only" in (conf_start, conf_end)
            or "csv+silence" in (conf_start, conf_end)
        )
        out.append(
            Segment(
                file_index=file_index,
                file_name=file_name,
                season=season,
                episode=ep,
                title=title,
                seg_index=i + 1,
                t_start_true=seg_starts_true[i],
                t_end_true=seg_ends_true[i],
                t_start_cut=seg_starts_cut[i],
                t_end_cut=seg_ends_cut[i],
                confidence_start=conf_start,
                confidence_end=conf_end,
                needs_review=needs_review,
            )
        )

    bstr = ", ".join(
        f"E{eps[i]}->{lib.format_timecode(boundaries_true[i])}"
        f"[{confidences[i]}]"
        for i in range(n - 1)
    )
    print(
        f"  file-{file_index:02d}: dur={dur:.0f}s  eps={eps}  "
        f"boundaries=[{bstr}]"
    )
    return out


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEASON
    state = lib.ensure_state_dir()
    mapping = load_mapping(season)
    csv_by_ep = csv_rows_by_season_episode(season)

    all_segments: list[Segment] = []
    duration_cache: dict = {}
    for row in mapping:
        try:
            segs = process_file(row, csv_by_ep, duration_cache)
        except Exception as e:
            print(
                f"  file-{row.get('file_index')}: ERROR {e!r}; "
                "skipping"
            )
            continue
        all_segments.extend(segs)

    out_path = state / f"timecodes_s{season}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file_index",
                "file_name",
                "season",
                "episode",
                "title",
                "seg_index",
                "t_start_true_s",
                "t_end_true_s",
                "t_start_true_hms",
                "t_end_true_hms",
                "t_start_cut_s",
                "t_end_cut_s",
                "confidence_start",
                "confidence_end",
                "needs_review",
            ]
        )
        for s in all_segments:
            w.writerow(
                [
                    s.file_index,
                    s.file_name,
                    s.season,
                    s.episode,
                    s.title,
                    s.seg_index,
                    f"{s.t_start_true:.3f}",
                    f"{s.t_end_true:.3f}",
                    lib.format_timecode(s.t_start_true),
                    lib.format_timecode(s.t_end_true),
                    f"{s.t_start_cut:.3f}",
                    f"{s.t_end_cut:.3f}",
                    s.confidence_start,
                    s.confidence_end,
                    "yes" if s.needs_review else "",
                ]
            )

    n_review = sum(1 for s in all_segments if s.needs_review)
    print(
        f"\nWrote {out_path}\n"
        f"Total segments: {len(all_segments)}; needs_review: {n_review}"
    )


if __name__ == "__main__":
    main()
