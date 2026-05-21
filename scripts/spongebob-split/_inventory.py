"""Inventory which S1-S5 episodes we have produced vs canonical totals."""
import csv
from pathlib import Path

# Canonical episode counts per season (per TVDB / Wikipedia production
# order). Each season's episodes are numbered 1..N consecutively.
CANONICAL: dict[int, int] = {
    1: 41,
    2: 40,
    3: 37,
    4: 38,
    5: 40,
}

ROOT = Path(r"C:\Users\Dante\Programming\Spongebob")

present: dict[int, set[int]] = {s: set() for s in CANONICAL}
for s in CANONICAL:
    csv_path = ROOT / f"timecodes_s{s}.csv"
    if not csv_path.exists():
        print(f"!! missing {csv_path}")
        continue
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            episode = int(row["episode"])
            if season in CANONICAL:
                present[season].add(episode)

print("=" * 60)
print("Missing episodes from Seasons 1-5")
print("=" * 60)
total_missing = 0
for s in sorted(CANONICAL):
    full = set(range(1, CANONICAL[s] + 1))
    missing = sorted(full - present[s])
    extras = sorted(present[s] - full)
    print(f"\nS{s:02d} ({len(present[s])} / {CANONICAL[s]} present)")
    if missing:
        compact = ",".join(f"E{e:02d}" for e in missing)
        print(f"  MISSING: {compact}")
    else:
        print("  MISSING: (none)")
    if extras:
        print(f"  Extras beyond canonical {CANONICAL[s]}: {extras}")
    total_missing += len(missing)
print(f"\nTotal missing across S1-S5: {total_missing}")
