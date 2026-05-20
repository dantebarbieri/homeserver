#!/usr/bin/env python3
"""Generate a fresh mapping_s{N}_template.csv based on actual file durations
(which reveal which files are single-episode vs combined blocks).

User edits the 'actual_episodes' column then renames to mapping_s{N}.csv.
"""

from __future__ import annotations

import csv
import sys

import lib

SINGLE_EPISODE_MAX_SECONDS = 900  # 15 min; real combined blocks are ~23min


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    state = lib.ensure_state_dir()
    files = lib.list_season_files(season)

    rows = lib.load_old_csv()
    blocks = lib.group_into_blocks(rows)
    s_blocks = [b for b in blocks if b.season == season]

    out_path = state / f"mapping_s{season}_template.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file_index",
                "file_name",
                "duration_s",
                "duration_hms",
                "likely_kind",
                "csv_guess_block",
                "csv_guess_episodes",
                "csv_guess_titles",
                "actual_episodes",
                "notes",
            ]
        )

        # Naive sequential guess that *skips* a CSV block whenever a file
        # looks single-episode (so the next combined file still aligns).
        block_iter = iter(s_blocks)
        next_block = next(block_iter, None)
        for i, path in enumerate(files, start=1):
            dur = lib.probe_duration(path)
            hms = f"{int(dur // 60)}:{int(dur % 60):02d}"
            if dur <= SINGLE_EPISODE_MAX_SECONDS:
                kind = "SINGLE"
                guess_block = ""
                guess_eps = ""
                guess_titles = ""
            else:
                kind = "COMBINED"
                if next_block is not None:
                    guess_block = (
                        f"E{next_block.first_episode:02d}-"
                        f"E{next_block.last_episode:02d}"
                    )
                    guess_eps = ",".join(
                        str(r.episode) for r in next_block.rows
                    )
                    guess_titles = " + ".join(
                        r.title for r in next_block.rows
                    )
                    next_block = next(block_iter, None)
                else:
                    guess_block = ""
                    guess_eps = ""
                    guess_titles = ""
            w.writerow(
                [
                    i,
                    path.name,
                    f"{dur:.1f}",
                    hms,
                    kind,
                    guess_block,
                    guess_eps,
                    guess_titles,
                    guess_eps,  # pre-fill; user edits
                    "",
                ]
            )
    print(f"Wrote {out_path}")
    print(
        "Edit 'actual_episodes' (comma-separated episode numbers in order), "
        "then rename to mapping_s{N}.csv"
    )


if __name__ == "__main__":
    main()
