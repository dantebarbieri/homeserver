"""Build a contact sheet (grid of thumbnails) per rescue file so the
user can scan for title cards quickly. Reads candidate JPGs produced
by 07_apply_fixes.py's SCAN action and produces one tall mosaic image
per file with each candidate as a single labelled thumbnail."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import lib

RESCUE_DIRS = [
    lib.STATE_DIR / "rescue_s4",
    lib.STATE_DIR / "rescue_s5",
]


def build_sheet_for_file(file_dir: Path) -> None:
    """Make `file_dir/contact.jpg`: 1 row per candidate, each row is a
    single 300px wide thumbnail labelled with index + timestamp."""
    cands = sorted(file_dir.glob("cand-*.jpg"))
    if not cands:
        return
    # Parse each filename: cand-NN-SSSSSs-H_MM_SS.mmm.jpg
    items: list[tuple[Path, int, float, str]] = []
    pat = re.compile(r"cand-(\d+)-(\d+)s-([\d_.]+)\.jpg")
    for p in cands:
        m = pat.match(p.name)
        if not m:
            continue
        items.append((p, int(m.group(1)), float(m.group(2)), m.group(3)))
    items.sort(key=lambda x: x[2])

    # For each candidate strip (12-frame hstack), extract just the
    # CENTRE frame (frame 6 of 12). Easier: use ffmpeg to crop the
    # original strip down to its middle 1/12.
    out = file_dir / "contact.jpg"
    # Build a vertical stack of cropped+labelled thumbnails. The
    # original strips are 200px tall; crop the central 1/12 and label.
    # For ffmpeg simplicity we build one big filter graph that crops,
    # adds a label box, then vstacks. Use 1-second of context = the
    # frame at time 0 in the strip = the 6th (centre) frame.
    inputs: list[str] = []
    labels: list[str] = []
    for i, (path, idx, t, hms) in enumerate(items):
        inputs.extend(["-i", str(path)])
        # Each strip is 12 frames hstacked at 200px tall.
        # Width = 12 * (frame_width). Centre frame is at x = 5/12 of width.
        # Crop 1/12 of width starting at 5/12.
        labels.append(
            f"[{i}:v]crop=iw/12:ih:5*iw/12:0,"
            f"drawtext=text='{idx:03d}  t\\={hms}':"
            f"fontcolor=white:fontsize=18:box=1:boxcolor=black@0.7:x=4:y=4"
            f",scale=300:-2[t{i}]"
        )
    concat = "".join(f"[t{i}]" for i in range(len(items)))
    fcomplex = ";".join(labels) + f";{concat}vstack=inputs={len(items)}[out]"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        fcomplex,
        "-map",
        "[out]",
        "-q:v",
        "3",
        str(out),
    ]
    print(f"  building {out} ({len(items)} candidates)")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        # Retry without drawtext if font isn't available.
        labels2 = []
        for i in range(len(items)):
            labels2.append(
                f"[{i}:v]crop=iw/12:ih:5*iw/12:0,scale=300:-2[t{i}]"
            )
        fcomplex2 = ";".join(labels2) + f";{concat}vstack=inputs={len(items)}[out]"
        cmd[-6] = fcomplex2
        subprocess.run(cmd, capture_output=True, text=True, check=False)
        print(f"  (no-drawtext fallback)")


def main() -> None:
    for rescue_root in RESCUE_DIRS:
        if not rescue_root.exists():
            continue
        for file_dir in sorted(rescue_root.iterdir()):
            if file_dir.is_dir() and file_dir.name.startswith("file-"):
                build_sheet_for_file(file_dir)


if __name__ == "__main__":
    main()
