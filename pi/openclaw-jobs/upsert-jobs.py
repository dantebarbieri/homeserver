#!/usr/bin/env python3
"""upsert-jobs.py — merge travel-agent cron jobs into the live jobs.json,
keyed by 'name'. Preserves existing id + createdAtMs + state on update;
generates them on insert. Removes 'foo-cron-job-bar' if present.

Usage:
    upsert-jobs.py /home/openclaw/.openclaw/cron/jobs.json travel-jobs.json

Idempotent. Backs up the live file to jobs.json.bak-<timestamp> before
writing. Writes to a temp file + os.rename for atomicity.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path


def now_ms() -> int:
    return int(time.time() * 1000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("live", type=Path, help="path to live jobs.json")
    ap.add_argument("template", type=Path, help="path to travel-jobs.json")
    ap.add_argument(
        "--remove",
        action="append",
        default=["foo-cron-job-bar"],
        help="job names to delete (repeatable; default includes foo-cron-job-bar)",
    )
    args = ap.parse_args()

    if not args.live.exists():
        print(f"live file missing: {args.live}", file=sys.stderr)
        return 2
    if not args.template.exists():
        print(f"template missing: {args.template}", file=sys.stderr)
        return 2

    live = json.loads(args.live.read_text(encoding="utf-8"))
    template = json.loads(args.template.read_text(encoding="utf-8"))

    if "jobs" not in live or not isinstance(live["jobs"], list):
        print("live jobs.json missing 'jobs' array", file=sys.stderr)
        return 3
    if "jobs" not in template or not isinstance(template["jobs"], list):
        print("template missing 'jobs' array", file=sys.stderr)
        return 3

    live_by_name = {j.get("name"): i for i, j in enumerate(live["jobs"])}
    now = now_ms()
    added, updated, removed = [], [], []

    # Remove any names requested for deletion.
    keep = []
    for j in live["jobs"]:
        if j.get("name") in args.remove:
            removed.append(j.get("name"))
            continue
        keep.append(j)
    live["jobs"] = keep
    live_by_name = {j.get("name"): i for i, j in enumerate(live["jobs"])}

    # Upsert each template job.
    for tpl in template["jobs"]:
        name = tpl.get("name")
        if not name:
            print(f"template job missing name, skipping: {tpl!r}", file=sys.stderr)
            continue

        # Build the volatile fields.
        if tpl.get("schedule", {}).get("kind") == "every":
            tpl.setdefault("schedule", {})["anchorMs"] = now

        if name in live_by_name:
            # Update in place — preserve id, createdAtMs, state.
            i = live_by_name[name]
            prior = live["jobs"][i]
            merged = {
                **tpl,
                "id": prior.get("id") or str(uuid.uuid4()),
                "createdAtMs": prior.get("createdAtMs") or now,
                "updatedAtMs": now,
            }
            if "state" in prior:
                merged["state"] = prior["state"]
            live["jobs"][i] = merged
            updated.append(name)
        else:
            merged = {
                **tpl,
                "id": str(uuid.uuid4()),
                "createdAtMs": now,
                "updatedAtMs": now,
            }
            live["jobs"].append(merged)
            added.append(name)

    # Backup + atomic write.
    bak = args.live.with_name(f"{args.live.name}.bak-{now}")
    shutil.copy2(args.live, bak)
    tmp = args.live.with_name(f"{args.live.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(live, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.rename(tmp, args.live)

    print(f"backup:  {bak}")
    print(f"added:   {added}")
    print(f"updated: {updated}")
    print(f"removed: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
