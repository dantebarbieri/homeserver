"""Apply per-segment timecode fixes based on user verify-strip feedback.

For each (season, episode) entry in OVERRIDES we adjust the segment's
true start time:

  * float offset (seconds) - shift the existing boundary by this much.
    Positive shifts the cut LATER (handle "too early" / title appears
    several frames into the output).
  * 'TOO_LATE'              - shift earlier by 8s (heuristic for when
                              title is gone and opening credits visible
                              at output start).
  * 'REDETECT'              - re-run blackdetect+silencedetect over a
                              MUCH wider window (+-90s) with a "prefer
                              earliest valid signal" policy, then snap.

After patching, we update the affected segment's start AND the
previous-segment-in-file's end (changing a boundary affects two
outputs), rewrite timecodes_s{N}.csv, re-cut both outputs with
ffmpeg, and regenerate their verify strips.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import lib
from importlib import import_module

# Import the existing processor module so we can re-use its helpers.
_06 = import_module("06_process_season")


# (season, episode) -> action
# Frame indices in 6-frame verify strips correspond to t = 0, 2, 4, 6,
# 8, 10 seconds (frame 1 .. frame 6). So "title at frame N" means the
# title card appeared at t = 2*(N-1) seconds into the output, which is
# how many seconds we need to shift the cut LATER.
OVERRIDES: dict[tuple[int, int], float | str] = {
    # Round 5 final touch-ups.
    (5, 39): +7.0,                  # title at frames 4 & 5
    (5, 2): +6.0,                   # title at frame 4
    (5, 30): "ABS:0:11:44.500",     # user-provided, replacing the 17:37 guess
    (4, 4): -3.0,                   # frame late, try -3
}

TOO_LATE_SHIFT = -8.0
WIDE_WINDOW = 90.0


def wider_detect(src: Path, estimate: float, duration: float) -> tuple[float, str]:
    """Re-run black/silence detection over +-WIDE_WINDOW around estimate,
    preferring the EARLIEST black+silence intersection that lies AT or
    AFTER (estimate - WIDE_WINDOW). This avoids the late-bias of
    picking the closest signal to the estimate when the estimate is
    itself wrong."""
    t_lo = max(1.0, estimate - WIDE_WINDOW)
    t_hi = min(duration - 1.0, estimate + WIDE_WINDOW)
    blacks, silences = _06.detect_signals(src, t_lo, t_hi)

    # Earliest black+silence overlap.
    best: tuple[float, str] | None = None
    for bs, be in sorted(blacks):
        for ss, se in silences:
            if se >= bs and ss <= be:
                if best is None or be < best[0]:
                    best = (be, "wide:black+silence")
    if best is not None:
        return best

    # Earliest black-only.
    for bs, be in sorted(blacks):
        if best is None or be < best[0]:
            best = (be, "wide:black-only")
    if best is not None:
        return best

    # Earliest silence-only.
    for ss, se in sorted(silences):
        if best is None or se < best[0]:
            best = (se, "wide:silence-only")
    if best is not None:
        return best

    return estimate, "wide:estimate-only"


def snap_to_keyframe_nearest(src: Path, t: float, duration: float) -> float:
    """Nearest keyframe within +-5s of t. Falls back to t if none found."""
    t_lo = max(0.0, t - 5.0)
    t_hi = min(duration, t + 5.0)
    kfs = _06.keyframes_in_range(src, t_lo, t_hi)
    if not kfs:
        return t
    return min(kfs, key=lambda k: abs(k - t))


def snap_to_keyframe_le(src: Path, t: float, duration: float) -> float:
    """Largest keyframe <= t. Falls back to t if none found."""
    t_lo = max(0.0, t - 20.0)
    t_hi = min(duration, t + 0.5)
    kfs = [k for k in _06.keyframes_in_range(src, t_lo, t_hi) if k <= t + 0.01]
    if not kfs:
        return t
    return max(kfs)



def load_csv(season: int) -> tuple[list[dict[str, str]], list[str]]:
    path = lib.STATE_DIR / f"timecodes_s{season}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fields


def save_csv(season: int, rows: list[dict[str, str]], fields: list[str]) -> None:
    path = lib.STATE_DIR / f"timecodes_s{season}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def find_row(
    rows: list[dict[str, str]], season: int, episode: int
) -> tuple[int, dict[str, str]] | None:
    for i, r in enumerate(rows):
        if int(r["season"]) == season and int(r["episode"]) == episode:
            return i, r
    return None


def find_predecessor(
    rows: list[dict[str, str]], idx: int
) -> tuple[int, dict[str, str]] | None:
    """The row immediately before idx in the SAME source file."""
    if idx == 0:
        return None
    cand = rows[idx - 1]
    if cand["file_name"] != rows[idx]["file_name"]:
        return None
    return idx - 1, cand


def apply_override(
    season: int, rows: list[dict[str, str]], idx: int, action: float | str,
    src_dir: Path,
) -> tuple[bool, str]:
    row = rows[idx]
    src = src_dir / row["file_name"]
    duration = lib.probe_duration(src)
    t_start_true_old = float(row["t_start_true_s"])

    if isinstance(action, (int, float)):
        new_true = t_start_true_old + float(action)
        new_tag = f"manual:{'+' if action > 0 else ''}{action:g}"
    elif isinstance(action, str) and action.startswith("ABS:"):
        # Format "ABS:<seconds_or_HMS>" e.g. "ABS:720.5" or "ABS:12:30"
        spec = action[4:]
        try:
            new_true = float(spec)
        except ValueError:
            new_true = lib.parse_timecode(spec) or 0.0
        new_tag = f"manual:abs={new_true:.2f}"
    elif action == "TOO_LATE":
        new_true = t_start_true_old + TOO_LATE_SHIFT
        new_tag = f"manual:{TOO_LATE_SHIFT:+g}"
    elif action == "REDETECT":
        new_true, new_tag = wider_detect(src, t_start_true_old, duration)
    else:
        return False, f"unknown action {action!r}"

    new_true = max(0.5, min(duration - 1.0, new_true))
    # Snap policy: for negative shifts and ABS overrides, snap to the
    # nearest keyframe so we don't drift past the title card (the
    # previous forward-only snap added 0-2s per pass and overshot the
    # title for several of these cases). For positive shifts we still
    # prefer forward snap to avoid bleeding into the previous segment.
    if isinstance(action, (int, float)) and action > 0:
        new_cut = _06.snap_to_keyframe_ge(src, new_true, duration)
    else:
        new_cut = snap_to_keyframe_nearest(src, new_true, duration)
    row["t_start_true_s"] = f"{new_true:.3f}"
    row["t_start_cut_s"] = f"{new_cut:.3f}"
    row["t_start_cut_hms"] = lib.format_timecode(new_cut)
    row["confidence_start"] = new_tag
    row["needs_review"] = ""  # cleared - user verified once we re-cut

    pred = find_predecessor(rows, idx)
    if pred is not None:
        _, prow = pred
        prow["t_end_true_s"] = f"{new_true:.3f}"
        prow["t_end_cut_s"] = f"{new_true:.3f}"
        prow["t_end_cut_hms"] = lib.format_timecode(new_true)
        prow["confidence_end"] = new_tag
    return True, f"true={new_true:.2f}s cut={new_cut:.2f}s ({new_tag})"


def re_cut_row(row: dict[str, str], season: int) -> str:
    src_dir = lib.SHOW_DIR / f"Season {season:02d}"
    src = src_dir / row["file_name"]
    season_out = int(row["season"])
    episode_out = int(row["episode"])
    title = row["title"]
    start = float(row["t_start_cut_s"])
    end = float(row["t_end_cut_s"])
    dst_dir = lib.SHOW_DIR / f"Season {season:02d} - split"
    out_path = dst_dir / lib.output_filename(season_out, episode_out, title)
    cmd = _06.split_command(src, out_path, start, end, title)
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        return f"ERROR: {e.stderr.strip().splitlines()[-1] if e.stderr else e}"
    try:
        dur = lib.probe_duration(out_path)
    except Exception as e:  # noqa: BLE001
        return f"ERROR validating: {e!r}"
    expected = end - start
    drift = abs(dur - expected)
    return f"OK dur={dur:.1f}s expected={expected:.1f}s drift={drift:.2f}"


def make_verify_strip(row: dict[str, str], season: int) -> None:
    season_out = int(row["season"])
    episode_out = int(row["episode"])
    title = row["title"]
    file_index = int(row["file_index"])
    dst_dir = lib.SHOW_DIR / f"Season {season:02d} - split"
    out_path = dst_dir / lib.output_filename(season_out, episode_out, title)
    strip_dir = lib.STATE_DIR / f"verify_s{season}"
    strip_dir.mkdir(exist_ok=True)
    strip_path = strip_dir / f"S{season_out:02d}E{episode_out:02d}-f{file_index:02d}.jpg"
    try:
        _06.make_verify_strip(out_path, strip_path)
    except Exception as e:  # noqa: BLE001
        print(f"  verify strip fail: {e!r}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Group overrides by SOURCE season (= which timecodes CSV the row
    # lives in), which may differ from the episode's target season for
    # cross-season splits like S02 file-14 (S03-3,4).
    by_source_season: dict[int, list[tuple[int, int, float | str]]] = {}
    for (s, e), action in OVERRIDES.items():
        src_season = _find_source_season(s, e)
        if src_season is None:
            print(
                f"!! could not locate S{s:02d}E{e:02d} in any "
                f"timecodes_sN.csv -- skipping",
                file=sys.stderr,
            )
            continue
        by_source_season.setdefault(src_season, []).append((s, e, action))

    for season in sorted(by_source_season):
        print(f"\n=== Season {season} (source) ===")
        rows, fields = load_csv(season)
        src_dir = lib.SHOW_DIR / f"Season {season:02d}"
        changed_idxs: set[int] = set()
        # Files that need whole-file candidate-strip generation.
        scan_files: dict[int, str] = {}  # file_index -> file_name
        for target_season, episode, action in by_source_season[season]:
            found = find_row(rows, target_season, episode)
            if found is None:
                print(
                    f"  S{target_season:02d}E{episode:02d}: NOT FOUND "
                    f"in timecodes_s{season}.csv (unexpected)"
                )
                continue
            idx, row = found
            if action == "SCAN":
                fi = int(row["file_index"])
                scan_files[fi] = row["file_name"]
                print(
                    f"  S{target_season:02d}E{episode:02d}: queued SCAN "
                    f"on file-{fi:02d}"
                )
                continue
            ok, msg = apply_override(season, rows, idx, action, src_dir)
            print(f"  S{target_season:02d}E{episode:02d}: {msg}")
            if ok:
                changed_idxs.add(idx)
                pred = find_predecessor(rows, idx)
                if pred is not None:
                    changed_idxs.add(pred[0])
        if args.dry_run:
            continue
        save_csv(season, rows, fields)
        for idx in sorted(changed_idxs):
            row = rows[idx]
            print(
                f"  re-cut S{int(row['season']):02d}E{int(row['episode']):02d} "
                f"from file-{int(row['file_index']):02d}: ",
                end="",
            )
            print(re_cut_row(row, season))
            make_verify_strip(row, season)
        if scan_files:
            scan_out = lib.STATE_DIR / f"rescue_s{season}"
            for fi in sorted(scan_files):
                src = src_dir / scan_files[fi]
                run_scan_for_file(src, fi, season, scan_out)


def _find_source_season(target_season: int, episode: int) -> int | None:
    """Search S1-S5 timecodes csvs for a row matching (target_season,
    episode). Returns the source season whose CSV contains the row, or
    None if not found."""
    for src_s in (1, 2, 3, 4, 5):
        path = lib.STATE_DIR / f"timecodes_s{src_s}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (
                    int(row["season"]) == target_season
                    and int(row["episode"]) == episode
                ):
                    return src_s
    return None


def whole_file_candidates(src: Path, duration: float) -> list[float]:
    """Return ALL black+silence intersection midpoints found in the file
    plus all black-only midpoints (looser thresholds). Sorted ascending,
    deduped to within 5s."""
    # Looser thresholds than 06_process_season because the standard
    # ones missed the real boundaries entirely for these problem files.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-ss",
        "30",
        "-to",
        f"{duration - 30:.3f}",
        "-i",
        str(src),
        "-vf",
        "blackdetect=d=0.05:pix_th=0.15",
        "-af",
        "silencedetect=noise=-30dB:d=0.20",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    blacks: list[tuple[float, float]] = []
    s_starts: list[float] = []
    s_ends: list[float] = []
    for line in proc.stderr.splitlines():
        m = _06._BLACK_RE.search(line)
        if m:
            blacks.append((30.0 + float(m.group(1)), 30.0 + float(m.group(2))))
            continue
        m = _06._SILENCE_START_RE.search(line)
        if m:
            s_starts.append(30.0 + float(m.group(1)))
            continue
        m = _06._SILENCE_END_RE.search(line)
        if m:
            s_ends.append(30.0 + float(m.group(1)))
    n = min(len(s_starts), len(s_ends))
    silences = list(zip(s_starts[:n], s_ends[:n]))
    # Collect ALL black centres; mark those that also overlap silence.
    cands: list[float] = []
    for bs, be in blacks:
        bc = 0.5 * (bs + be)
        cands.append(bc)
    # Also include silence-only candidates that DON'T overlap any black,
    # so we don't miss boundaries where the fade was very short.
    for ss, se in silences:
        if not any(b_e >= ss and b_s <= se for b_s, b_e in blacks):
            cands.append(0.5 * (ss + se))
    cands.sort()
    # Dedupe within 5s.
    deduped: list[float] = []
    for t in cands:
        if not deduped or t - deduped[-1] >= 5.0:
            deduped.append(round(t, 1))
    return deduped


def make_candidate_strip(
    src: Path, t: float, duration: float, out_path: Path
) -> None:
    """12-frame horizontal strip centred on t, frames spaced 1.5s apart
    (covering ~16s of context). Frame names embed the timestamp."""
    offsets = [-7.5, -6.0, -4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0]
    inputs: list[str] = []
    for i, off in enumerate(offsets):
        ts = max(0.0, min(duration - 0.1, t + off))
        inputs.extend(["-ss", lib.format_timecode(ts), "-i", str(src)])
    scale_parts = ";".join(
        f"[{i}:v]scale=-2:200[v{i}]" for i in range(len(offsets))
    )
    concat = "".join(f"[v{i}]" for i in range(len(offsets)))
    fcomplex = (
        f"{scale_parts};{concat}hstack=inputs={len(offsets)}[out]"
    )
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
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=False)


def run_scan_for_file(
    src: Path, file_index: int, season: int, out_dir: Path
) -> Path:
    """Emit candidate strips for one source file. Returns the output
    directory containing per-candidate strips and an index.txt."""
    file_out = out_dir / f"file-{file_index:02d}"
    file_out.mkdir(parents=True, exist_ok=True)
    duration = lib.probe_duration(src)
    cands = whole_file_candidates(src, duration)
    print(
        f"  scan file-{file_index:02d} ({src.name}): "
        f"{len(cands)} candidates"
    )
    index_lines: list[str] = []
    for i, t in enumerate(cands):
        hms = lib.format_timecode(t).replace(":", "_")
        out_path = file_out / f"cand-{i:02d}-{int(t):05d}s-{hms}.jpg"
        make_candidate_strip(src, t, duration, out_path)
        index_lines.append(f"{i:02d}  t={t:7.2f}s  {hms}  {out_path.name}")
    (file_out / "candidates.txt").write_text("\n".join(index_lines) + "\n")
    return file_out


if __name__ == "__main__":
    main()
