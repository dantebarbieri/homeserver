"""Phase 3+4 for S2-S5: given a user-edited mapping_s{N}.csv, parse the
actual_episodes assignments, detect segment boundaries on the new files,
and stream-copy split each combined file into per-episode outputs.

Logic vs. the S1 pipeline (04_find_boundaries.py + 05_split_episodes.py):

  * `actual_episodes` is the user's authoritative cataloguing of what's
    in each file, in file order. Tokens may carry cross-season prefixes
    (`S03-12`) and specials (`S00-1`). Out-of-order is intentional.
  * Boundary seeds come from looking up each segment's expected duration
    in the OLD csv (`episode_meta.lookup_episode`). If durations are
    available we use them to estimate boundaries proportionally to the
    new file's actual length. If not, we fall back to equal-length
    splits.
  * Boundary refinement uses blackdetect + silencedetect in a +-30s
    window around each estimate. Tiered confidence: black+silence ->
    black only -> silence only -> the estimate itself.
  * SINGLE files: if the episode also appears in a COMBINED file's
    actual_episodes elsewhere this season, the single is SKIPPED (we
    re-derive from the combined, matching the S1 Pickles/Opposite Day
    decision). Otherwise the single is COPIED with a Sonarr-style name.
  * COMBINED files whose actual_episodes has exactly one entry (e.g.
    full-length specials) are also COPIED, not split.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import episode_meta
import episode_parser
import lib


# Detection thresholds (kept consistent with 02_make_titlecard_strips
# and 04_find_boundaries).
BLACK_MIN_DURATION = 0.20
BLACK_PIX_THRESHOLD = 0.10
SILENCE_MIN_DURATION = 0.40
SILENCE_DB = -40

# Window (seconds) around an estimated boundary in which to look for a
# real one. Wider than S1's +-25s because uncatalogued seasons rely on
# proportional estimates which are noisier.
SEARCH_WINDOW = 30.0


# ---------------------------------------------------------------------------
# Mapping CSV parsing
# ---------------------------------------------------------------------------


@dataclass
class FileSpec:
    file_index: int
    file_name: str
    src: Path
    duration: float
    likely_kind: str  # SINGLE | COMBINED (from template, advisory only)
    episodes: list[tuple[int, int]]  # in file order
    notes: str

    @property
    def n_segments(self) -> int:
        return len(self.episodes)


def load_mapping(season: int) -> list[FileSpec]:
    path = lib.STATE_DIR / f"mapping_s{season}.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    src_dir = lib.SHOW_DIR / f"Season {season:02d}"
    out: list[FileSpec] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            src = src_dir / row["file_name"]
            if not src.exists():
                print(f"!! missing source: {src}", file=sys.stderr)
                continue
            episodes = episode_parser.parse_actual_episodes(
                row.get("actual_episodes", ""), default_season=season
            )
            out.append(
                FileSpec(
                    file_index=int(row["file_index"]),
                    file_name=row["file_name"],
                    src=src,
                    duration=float(row["duration_s"]),
                    likely_kind=row.get("likely_kind", "COMBINED"),
                    episodes=episodes,
                    notes=row.get("notes", ""),
                )
            )
    return out


# ---------------------------------------------------------------------------
# Boundary detection (ffmpeg)
# ---------------------------------------------------------------------------


_BLACK_RE = re.compile(
    r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)"
)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(\d+(?:\.\d+)?)")


def detect_signals(
    src: Path, t_lo: float, t_hi: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Run blackdetect + silencedetect in one ffmpeg pass over [t_lo, t_hi].
    Returns (blacks, silences), each as absolute [start, end] intervals."""
    duration = t_hi - t_lo
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-ss",
        f"{t_lo:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src),
        "-vf",
        f"blackdetect=d={BLACK_MIN_DURATION}:pix_th={BLACK_PIX_THRESHOLD}",
        "-af",
        f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_DURATION}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # ffmpeg detection failure: surface the last stderr line for
        # diagnosis. Returning empty signals means we'll fall back to
        # estimate-only with needs_review=True for the affected segment.
        tail = (
            proc.stderr.strip().splitlines()[-1]
            if proc.stderr.strip()
            else "(no stderr)"
        )
        print(
            f"!! detect_signals failed for {src.name} "
            f"[{t_lo:.1f}-{t_hi:.1f}s]: {tail}",
            file=sys.stderr,
        )
        return [], []
    blacks: list[tuple[float, float]] = []
    s_starts: list[float] = []
    s_ends: list[float] = []
    for line in proc.stderr.splitlines():
        m = _BLACK_RE.search(line)
        if m:
            blacks.append(
                (t_lo + float(m.group(1)), t_lo + float(m.group(2)))
            )
            continue
        m = _SILENCE_START_RE.search(line)
        if m:
            s_starts.append(t_lo + float(m.group(1)))
            continue
        m = _SILENCE_END_RE.search(line)
        if m:
            s_ends.append(t_lo + float(m.group(1)))
    n = min(len(s_starts), len(s_ends))
    silences = list(zip(s_starts[:n], s_ends[:n]))
    return blacks, silences


def find_boundary(
    src: Path, estimate: float, duration: float
) -> tuple[float, str]:
    """Return (boundary_seconds, confidence_tag) near estimate.

    The boundary is the END of the black/silence interval (= start of
    the fade-in to the new episode's title card), so keyframe-snap-
    forward lands ON the title card rather than the previous credits.
    """
    t_lo = max(1.0, estimate - SEARCH_WINDOW)
    t_hi = min(duration - 1.0, estimate + SEARCH_WINDOW)
    blacks, silences = detect_signals(src, t_lo, t_hi)

    # Tier 1: black + silence overlap -> very high confidence. Use
    # the end of black (be) as the boundary so keyframe-snap-forward
    # lands on the new episode's title card rather than its silent
    # cold-open (silence alone may extend past the title card into a
    # quiet opening line). Silence here is corroboration only.
    best: tuple[float, str] | None = None
    best_score = float("inf")
    for bs, be in blacks:
        for ss, se in silences:
            if se >= bs and ss <= be:
                score = abs(be - estimate)
                if score < best_score:
                    best_score = score
                    best = (be, "black+silence")
    if best is not None:
        return best

    # Tier 2: blackdetect only. Same logic - use end-of-black.
    for bs, be in blacks:
        score = abs(be - estimate)
        if score < best_score:
            best_score = score
            best = (be, "black-only")
    if best is not None:
        return best

    # Tier 3: silence only - require small drift (user noted silence
    # alone is the most common false positive source). Use end-of-
    # silence, but still risky.
    for ss, se in silences:
        score = abs(se - estimate)
        if score < min(best_score, 8.0):
            best_score = score
            best = (se, "silence-only")
    if best is not None:
        return best

    return estimate, "estimate-only"


# ---------------------------------------------------------------------------
# Keyframe snapping (forward / >= true boundary)
# ---------------------------------------------------------------------------


def keyframes_in_range(src: Path, t_lo: float, t_hi: float) -> list[float]:
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
        "default=nw=1:nk=1",
        str(src),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out: list[float] = []
    for line in proc.stdout.splitlines():
        try:
            out.append(float(line.strip()))
        except ValueError:
            pass
    return out


def snap_to_keyframe_ge(src: Path, t: float, duration: float) -> float:
    t_lo = max(0.0, t - 0.5)
    t_hi = min(duration, t + 20.0)
    kfs = [k for k in keyframes_in_range(src, t_lo, t_hi) if k >= t - 0.01]
    if not kfs:
        return t
    return min(kfs)


# ---------------------------------------------------------------------------
# Boundary estimation per file (proportional to old CSV durations)
# ---------------------------------------------------------------------------


def estimate_boundaries(
    episodes: list[tuple[int, int]], file_duration: float
) -> list[float]:
    """Return the N-1 boundary times for N segments inside a combined file.

    Uses old-CSV durations when available. For segments without known
    durations, allocates the remaining file time equally among them
    (weighted partial estimation). Falls back to full equal split only
    when nothing is known.
    """
    n = len(episodes)
    if n < 2:
        return []
    durs: list[float | None] = [
        episode_meta.lookup_episode(s, e).old_duration_s for s, e in episodes
    ]
    known = [d for d in durs if d is not None]
    if not known:
        return [file_duration * (i + 1) / n for i in range(n - 1)]
    known_total = sum(known)
    unknown_count = sum(d is None for d in durs)
    if unknown_count == 0:
        # All known: scale-to-fit to absorb release-specific length
        # differences (intro/outro variants, ad-break removal).
        scale = file_duration / known_total if known_total > 0 else 1.0
        effective = [d * scale for d in durs]  # type: ignore[operator]
    else:
        # Some known: hold known durations, split remainder equally.
        remainder = max(0.0, file_duration - known_total)
        unknown_dur = remainder / unknown_count
        effective = [d if d is not None else unknown_dur for d in durs]
    cumulative = 0.0
    boundaries: list[float] = []
    for i in range(n - 1):
        cumulative += effective[i]
        boundaries.append(cumulative)
    return boundaries


# ---------------------------------------------------------------------------
# Output planning
# ---------------------------------------------------------------------------


@dataclass
class OutSegment:
    season: int
    episode: int
    title: str
    src: Path
    file_index: int
    seg_index: int  # 1-based within source file
    t_start_true: float
    t_end_true: float
    t_start_cut: float
    t_end_cut: float
    confidence_start: str
    confidence_end: str
    needs_review: bool = False
    note: str = ""


def plan_segments(specs: list[FileSpec], season: int) -> list[OutSegment]:
    # First, find every (season, episode) that appears as a segment of
    # a COMBINED (>=2 segments) file. Those are derived from splits.
    combined_eps: set[tuple[int, int]] = set()
    for sp in specs:
        if sp.n_segments >= 2:
            combined_eps.update(sp.episodes)

    out: list[OutSegment] = []
    for sp in specs:
        if sp.n_segments == 0:
            print(f"-- file-{sp.file_index:02d}: no actual_episodes, SKIP")
            continue
        if sp.n_segments == 1:
            ep_se = sp.episodes[0]
            if ep_se in combined_eps:
                print(
                    f"-- file-{sp.file_index:02d}: SINGLE for "
                    f"S{ep_se[0]:02d}E{ep_se[1]:02d} duplicates a "
                    f"COMBINED-derived split; SKIP"
                )
                continue
            meta = episode_meta.lookup_episode(*ep_se)
            print(
                f"-- file-{sp.file_index:02d}: SINGLE "
                f"S{ep_se[0]:02d}E{ep_se[1]:02d} '{meta.title}'; COPY"
            )
            out.append(
                OutSegment(
                    season=ep_se[0],
                    episode=ep_se[1],
                    title=meta.title,
                    src=sp.src,
                    file_index=sp.file_index,
                    seg_index=1,
                    t_start_true=0.0,
                    t_end_true=sp.duration,
                    t_start_cut=0.0,
                    t_end_cut=sp.duration,
                    confidence_start="whole-file",
                    confidence_end="whole-file",
                    needs_review=False,
                    note=sp.notes,
                )
            )
            continue
        # COMBINED: estimate boundaries, refine, snap, build segments.
        estimates = estimate_boundaries(sp.episodes, sp.duration)
        true_starts: list[float] = [0.0]
        confidences_start: list[str] = ["start-of-file"]
        needs_review_per_boundary: list[bool] = [False]
        for est in estimates:
            t_true, conf = find_boundary(sp.src, est, sp.duration)
            true_starts.append(t_true)
            confidences_start.append(conf)
            # Flag if we drifted a lot or fell back.
            needs_review_per_boundary.append(
                conf in ("silence-only", "estimate-only")
                or abs(t_true - est) > 10.0
            )
        true_ends = true_starts[1:] + [sp.duration]
        # Keyframe-snap segment starts forward (matches S1 final
        # policy: avoid bleed-in from prior segment).
        cut_starts: list[float] = []
        for ts in true_starts:
            if ts <= 0.5:
                cut_starts.append(0.0)
            else:
                cut_starts.append(snap_to_keyframe_ge(sp.src, ts, sp.duration))
        cut_ends: list[float] = true_ends  # unchanged
        for i, (sea_ep, ts, te, cs, ce, conf_s) in enumerate(
            zip(
                sp.episodes,
                true_starts,
                true_ends,
                cut_starts,
                cut_ends,
                confidences_start,
            )
        ):
            meta = episode_meta.lookup_episode(*sea_ep)
            out.append(
                OutSegment(
                    season=sea_ep[0],
                    episode=sea_ep[1],
                    title=meta.title,
                    src=sp.src,
                    file_index=sp.file_index,
                    seg_index=i + 1,
                    t_start_true=ts,
                    t_end_true=te,
                    t_start_cut=cs,
                    t_end_cut=ce,
                    confidence_start=conf_s,
                    confidence_end=(
                        "end-of-file"
                        if i == len(sp.episodes) - 1
                        else confidences_start[i + 1]
                    ),
                    needs_review=(
                        needs_review_per_boundary[i]
                        or (
                            i + 1 < len(needs_review_per_boundary)
                            and needs_review_per_boundary[i + 1]
                        )
                    ),
                    note=sp.notes,
                )
            )
    # Verify uniqueness: each (season, episode) should be planned once.
    seen: dict[tuple[int, int], OutSegment] = {}
    dupes: list[tuple[OutSegment, OutSegment]] = []
    for seg in out:
        key = (seg.season, seg.episode)
        if key in seen:
            dupes.append((seen[key], seg))
        else:
            seen[key] = seg
    if dupes:
        msg_lines = ["DUPLICATE (season, episode) outputs planned:"]
        for a, b in dupes:
            msg_lines.append(
                f"  S{a.season:02d}E{a.episode:02d}: "
                f"file-{a.file_index:02d} seg-{a.seg_index} AND "
                f"file-{b.file_index:02d} seg-{b.seg_index}"
            )
        raise RuntimeError("\n".join(msg_lines))
    return out


# ---------------------------------------------------------------------------
# CSV writer (timecodes_s{N}.csv) and splitter (ffmpeg)
# ---------------------------------------------------------------------------


def write_timecodes_csv(segments: list[OutSegment], season: int) -> Path:
    path = lib.STATE_DIR / f"timecodes_s{season}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file_index",
                "seg_index",
                "file_name",
                "season",
                "episode",
                "title",
                "t_start_true_s",
                "t_end_true_s",
                "t_start_cut_s",
                "t_end_cut_s",
                "t_start_cut_hms",
                "t_end_cut_hms",
                "confidence_start",
                "confidence_end",
                "needs_review",
                "note",
            ]
        )
        for s in segments:
            w.writerow(
                [
                    s.file_index,
                    s.seg_index,
                    s.src.name,
                    s.season,
                    s.episode,
                    s.title,
                    f"{s.t_start_true:.3f}",
                    f"{s.t_end_true:.3f}",
                    f"{s.t_start_cut:.3f}",
                    f"{s.t_end_cut:.3f}",
                    lib.format_timecode(s.t_start_cut),
                    lib.format_timecode(s.t_end_cut),
                    s.confidence_start,
                    s.confidence_end,
                    "yes" if s.needs_review else "",
                    s.note,
                ]
            )
    return path


def split_command(
    src: Path, out_path: Path, start: float, end: float, title: str
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-ss",
        lib.format_timecode(start),
        "-i",
        str(src),
        "-t",
        f"{end - start:.3f}",
        "-map",
        "0",
        "-map_chapters",
        "-1",
        "-c",
        "copy",
        "-c:s",
        "srt",
        "-avoid_negative_ts",
        "make_zero",
        "-disposition:a",
        "0",
        "-disposition:a:0",
        "default",
        "-disposition:s",
        "0",
        "-metadata",
        f"title={title}",
        str(out_path),
    ]


def copy_whole_command(
    src: Path, out_path: Path, title: str
) -> list[str]:
    """Copy a whole file with new name + title metadata, no cut.

    Keep chapters (whole-file chapters are still valid) and stream-copy
    subtitles (no boundary to clip)."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(src),
        "-map",
        "0",
        "-c",
        "copy",
        "-disposition:a",
        "0",
        "-disposition:a:0",
        "default",
        "-disposition:s",
        "0",
        "-metadata",
        f"title={title}",
        str(out_path),
    ]


def run_split(seg: OutSegment, out_path: Path, dry_run: bool) -> str:
    is_whole = (
        seg.confidence_start == "whole-file"
        and seg.confidence_end == "whole-file"
    )
    if is_whole:
        cmd = copy_whole_command(seg.src, out_path, seg.title)
    else:
        cmd = split_command(
            seg.src, out_path, seg.t_start_cut, seg.t_end_cut, seg.title
        )
    if dry_run:
        return "DRY-RUN " + " ".join(cmd)
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip().splitlines()[-1] if e.stderr else str(e)
        return f"ERROR: {msg}"
    try:
        out_dur = lib.probe_duration(out_path)
    except Exception as e:  # noqa: BLE001
        return f"ERROR validating: {e!r}"
    expected = seg.t_end_cut - seg.t_start_cut
    drift = abs(out_dur - expected)
    if is_whole:
        return f"OK whole-file  out_dur={out_dur:.1f}s"
    tag = "OK" if drift < 2.0 else f"WARN drift={drift:.2f}s"
    return f"{tag}  out_dur={out_dur:.1f}s  expected={expected:.1f}s"


# ---------------------------------------------------------------------------
# Verification strip (first 12s of each output, six frames)
# ---------------------------------------------------------------------------


def make_verify_strip(out_mkv: Path, strip_path: Path) -> None:
    """Hstack six frames at t = 0, 2, 4, 6, 8, 10 seconds of the output
    file. Used so the user can confirm a title card appears at the
    start (or close to it)."""
    offsets = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    inputs: list[str] = []
    fcomplex_parts: list[str] = []
    for i, off in enumerate(offsets):
        inputs.extend(["-ss", lib.format_timecode(off), "-i", str(out_mkv)])
        fcomplex_parts.append(
            f"[{i}:v]drawtext=text='%{{eif\\:t+{off}\\:d}}s':"
            f"fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:x=10:y=10,"
            f"scale=-2:240[v{i}]"
        )
    concat = "".join(f"[v{i}]" for i in range(len(offsets)))
    fcomplex = ";".join(fcomplex_parts) + f";{concat}hstack=inputs={len(offsets)}[out]"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-frames:v",
        "1",
        "-filter_complex",
        fcomplex,
        "-map",
        "[out]",
        "-q:v",
        "3",
        str(strip_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        # Re-try without drawtext if font is missing.
        fcomplex2 = ";".join(
            f"[{i}:v]scale=-2:240[v{i}]" for i in range(len(offsets))
        ) + f";{concat}hstack=inputs={len(offsets)}[out]"
        cmd[-6] = fcomplex2
        subprocess.run(cmd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-split", action="store_true", help="plan + write CSV only"
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--no-verify", action="store_true", help="skip verification strips"
    )
    args = ap.parse_args()

    specs = load_mapping(args.season)
    print(f"Loaded {len(specs)} files for Season {args.season}")

    segments = plan_segments(specs, args.season)
    csv_path = write_timecodes_csv(segments, args.season)
    print(f"Wrote {csv_path} ({len(segments)} segments)")
    flags = sum(1 for s in segments if s.needs_review)
    print(f"  needs_review: {flags}")

    if args.skip_split:
        return

    dst_dir = lib.SHOW_DIR / f"Season {args.season:02d} - split"
    dst_dir.mkdir(exist_ok=True)
    verify_dir = lib.STATE_DIR / f"verify_s{args.season}"
    verify_dir.mkdir(exist_ok=True)
    log_path = lib.STATE_DIR / f"split_s{args.season}.log"

    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            f"--- run dry={args.dry_run} force={args.force} ---\n"
        )
        for seg in segments:
            out_name = lib.output_filename(seg.season, seg.episode, seg.title)
            out_path = dst_dir / out_name
            if out_path.exists() and not args.force and not args.dry_run:
                status = "skip (exists; use --force to overwrite)"
            else:
                status = run_split(seg, out_path, args.dry_run)
                # Build a verification strip after successful split.
                if (
                    not args.dry_run
                    and not args.no_verify
                    and status.startswith(("OK", "WARN"))
                ):
                    strip_path = (
                        verify_dir
                        / f"S{seg.season:02d}E{seg.episode:02d}"
                        f"-f{seg.file_index:02d}.jpg"
                    )
                    try:
                        make_verify_strip(out_path, strip_path)
                    except Exception as e:  # noqa: BLE001
                        status += f" [verify-fail: {e!r}]"
            line = (
                f"[file-{seg.file_index:02d} seg-{seg.seg_index}] "
                f"S{seg.season:02d}E{seg.episode:02d} {seg.title!r} -> "
                f"{out_path.name} :: {status}"
            )
            print(line)
            log.write(line + "\n")
            log.flush()


if __name__ == "__main__":
    main()
