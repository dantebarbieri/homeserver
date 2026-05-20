"""Shared helpers for the SpongeBob splitter scripts.

All scripts in this directory assume they are run inside a `nix shell
nixpkgs#ffmpeg nixpkgs#python3` environment on the homeserver. No
third-party Python dependencies.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SHOW_DIR = Path(
    "/data/shared/media/tv/SpongeBob SquarePants (1999) {tvdb-75886}"
)
STATE_DIR = SHOW_DIR / "_split-state"
OLD_CSV = SHOW_DIR / "Spongebob Timecodes - Spongebob Timecodes.csv"


# ---------------------------------------------------------------------------
# CSV models
# ---------------------------------------------------------------------------


@dataclass
class OldRow:
    """One row from the legacy timecode CSV."""

    season: int
    episode: int
    title: str
    t_start: float | None  # seconds, None means "start of file"
    t_end: float | None  # seconds, None means "end of file"
    old_directory: str
    old_filename: str


@dataclass
class Block:
    """A group of OldRow segments that share an old combined filename.

    The list is ordered by episode number within the block.
    """

    season: int
    old_filename: str
    rows: list[OldRow] = field(default_factory=list)

    @property
    def first_episode(self) -> int:
        return self.rows[0].episode

    @property
    def last_episode(self) -> int:
        return self.rows[-1].episode

    @property
    def n_segments(self) -> int:
        return len(self.rows)


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)\s*$")


def parse_timecode(s: str) -> float | None:
    """Parse 'M:SS', 'MM:SS', 'H:MM:SS' (with optional .fraction). Empty -> None."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    m = _TIME_RE.match(s)
    if not m:
        # Allow bare seconds as a fallback.
        try:
            return float(s)
        except ValueError as e:
            raise ValueError(f"unparseable timecode: {s!r}") from e
    h, mi, se = m.groups()
    total = float(se) + int(mi) * 60
    if h is not None:
        total += int(h) * 3600
    return total


def format_timecode(seconds: float) -> str:
    """Format seconds as H:MM:SS.mmm for ffmpeg -ss/-to."""
    if seconds < 0:
        raise ValueError(f"negative timecode: {seconds}")
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:06.3f}"


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------


def load_old_csv(path: Path = OLD_CSV) -> list[OldRow]:
    rows: list[OldRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                OldRow(
                    season=int(r["Season"]),
                    episode=int(r["Episode"]),
                    title=r["Episode Title"].strip(),
                    t_start=parse_timecode(r["Timecode Start"]),
                    t_end=parse_timecode(r["Timecode End"]),
                    old_directory=r["Directory"].strip(),
                    old_filename=r["Filename"].strip(),
                )
            )
    return rows


def group_into_blocks(rows: Iterable[OldRow]) -> list[Block]:
    """Group rows by (season, old_filename), preserving CSV order."""
    blocks: dict[tuple[int, str], Block] = {}
    order: list[tuple[int, str]] = []
    for r in rows:
        key = (r.season, r.old_filename)
        if key not in blocks:
            blocks[key] = Block(season=r.season, old_filename=r.old_filename)
            order.append(key)
        blocks[key].rows.append(r)
    return [blocks[k] for k in order]


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe wrappers
# ---------------------------------------------------------------------------


def _require(tool: str) -> str:
    p = shutil.which(tool)
    if not p:
        raise RuntimeError(
            f"{tool!r} not found on PATH. Run inside "
            "`nix shell nixpkgs#ffmpeg nixpkgs#python3 -c bash`."
        )
    return p


def ffprobe_json(args: list[str]) -> dict:
    """Run ffprobe with -of json and return the parsed JSON."""
    cmd = [_require("ffprobe"), "-v", "error", "-of", "json", *args]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(res.stdout)


def probe_duration(path: Path) -> float:
    data = ffprobe_json(
        ["-show_entries", "format=duration", str(path)]
    )
    return float(data["format"]["duration"])


def probe_streams(path: Path) -> list[dict]:
    data = ffprobe_json(["-show_streams", str(path)])
    return data.get("streams", [])


def list_season_files(season: int) -> list[Path]:
    """Return the .mkv files in 'Season 0X/' sorted by Sonarr S0XEYY index."""
    season_dir = SHOW_DIR / f"Season {season:02d}"
    files = sorted(season_dir.glob("*.mkv"))
    return files


_EP_RE = re.compile(r"\bS(\d{2})E(\d{2,3})\b", re.IGNORECASE)


def sonarr_index(path: Path) -> tuple[int, int]:
    """Extract (season, episode_index) from a Sonarr filename."""
    m = _EP_RE.search(path.name)
    if not m:
        raise ValueError(f"no S/E marker in {path.name!r}")
    return int(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------------------
# Filesystem-safe title
# ---------------------------------------------------------------------------


_SANITIZE_RE = re.compile(r'[\\/:*?"<>|]+')


def sanitize_title(title: str) -> str:
    """Make a title safe as a filename component."""
    cleaned = _SANITIZE_RE.sub("", title).strip()
    # Collapse runs of whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def output_filename(season: int, episode: int, title: str) -> str:
    """Sonarr-style: 'SpongeBob SquarePants (1999) - S01E02 - Reef Blower.mkv'."""
    safe = sanitize_title(title)
    return (
        f"SpongeBob SquarePants (1999) - "
        f"S{season:02d}E{episode:02d} - {safe}.mkv"
    )


# ---------------------------------------------------------------------------
# State dir
# ---------------------------------------------------------------------------


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR
