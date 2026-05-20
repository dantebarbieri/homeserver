# SpongeBob episode splitter

Tools for splitting Sonarr's combined-block SpongeBob files (each ~23.5 min
file actually contains 2-3 episode segments) into per-segment files, using
`Spongebob Timecodes - Spongebob Timecodes.csv` (kept next to the show on
the RAID) as the source of truth for segment titles and approximate
boundaries.

See `plan.md` in the active Copilot session for the full design. Quick
reference:

```
# Show directory on the server:
SHOW="/data/shared/media/tv/SpongeBob SquarePants (1999) {tvdb-75886}"
STATE="$SHOW/_split-state"

# All commands run inside a nix shell:
nix shell nixpkgs#ffmpeg nixpkgs#python3 -c bash
```

## Scripts

| Script | Phase | Purpose |
|--------|-------|---------|
| `lib.py`               | shared | CSV parsing, ffprobe/ffmpeg helpers, title sanitization |
| `01_map_blocks.py`     | 2 | Verify which old CSV block lives in each new file; emit `mapping.csv` |
| `02_find_boundaries.py`| 3 | Re-derive segment boundaries on new files; emit `timecodes_new.csv` |
| `03_split_episodes.py` | 4-5 | Stream-copy splitter that consumes `timecodes_new.csv` |

State files (mapping CSV, boundary CSV, logs, thumbnails) live in
`$STATE`, NOT in this repo.
