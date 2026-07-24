#!/usr/bin/env python3
"""Mirror a Plex library's folder structure into collections.

Movie-type Plex libraries flatten everything into one alphabetical list;
this script recreates the on-disk folder hierarchy as collections (like
Jellyfin's native folder view). Re-run after adding files — it is
idempotent: creates missing collections, adds new items, removes items
whose files moved elsewhere.

Optionally (--retitle) it also gives readable titles and release dates to
items whose filenames are camera timestamps (e.g. 20081017182521.m2ts →
"2008-10-17 18:25"). Only items whose title still equals the filename are
touched, so manual titles are never clobbered; edited fields are locked so
Plex refreshes don't undo them.

Run on the server (no system python — use nix-shell):
    nix-shell -p python3 --run \
        '/srv/homeserver/docker/scripts/plex-folder-collections.py [--dry-run] [--retitle]'

The Plex token is read from the running plex container's Preferences.xml
(requires docker access); override with PLEX_TOKEN env var.
Library selection: --library "Our Videos" (default).
"""

import argparse
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PLEX_URL = os.environ.get("PLEX_URL", "http://127.0.0.1:32400")

# Filename patterns that encode a recording timestamp.
TS_PATTERNS = [
    re.compile(r"^(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})(?P<h>\d{2})(?P<m>\d{2})\d{2}$"),
    re.compile(r"^(?P<Y>\d{4})-(?P<M>\d{2})-(?P<D>\d{2}) (?P<h>\d{2})\.(?P<m>\d{2})\.\d{2}$"),
    re.compile(r"^VID[_-](?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})[_-](?P<h>\d{2})(?P<m>\d{2})\d{2}( - Copy)?$"),
    re.compile(r"^VID-(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})-WA\d+$"),
    re.compile(r"^(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})_(?P<h>\d{2})(?P<m>\d{2})\d{2}$"),
    re.compile(r"^video-(?P<Y>\d{4})-(?P<M>\d{2})-(?P<D>\d{2})-(?P<h>\d{2})-(?P<m>\d{2})-\d{2}$"),
]


def plex_token():
    tok = os.environ.get("PLEX_TOKEN")
    if tok:
        return tok
    out = subprocess.run(
        ["docker", "exec", "plex", "sed", "-n",
         's/.*PlexOnlineToken="\\([^"]*\\)".*/\\1/p',
         "/config/Library/Application Support/Plex Media Server/Preferences.xml"],
        capture_output=True, text=True, check=True)
    tok = out.stdout.strip()
    if not tok:
        sys.exit("Could not read Plex token from container; set PLEX_TOKEN")
    return tok


TOKEN = None


def api(method, path, params=None):
    params = dict(params or {})
    params["X-Plex-Token"] = TOKEN
    url = f"{PLEX_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method=method,
                                 headers={"X-Plex-Container-Size": "10000"})
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
    return ET.fromstring(body) if body.strip() else None


def find_section(name):
    for d in api("GET", "/library/sections").iter("Directory"):
        if d.get("title") == name:
            root = d.find("Location").get("path")
            return d.get("key"), root
    sys.exit(f"Library '{name}' not found")


def library_items(section, root):
    """-> {ratingKey: (title, relative dir, filename stem)}"""
    items = {}
    for v in api("GET", f"/library/sections/{section}/all", {"type": 1}).iter("Video"):
        part = v.find("./Media/Part")
        if part is None:
            continue
        file = part.get("file")
        if not file.startswith(root.rstrip("/") + "/"):
            continue
        rel = os.path.relpath(os.path.dirname(file), root)
        if rel == ".":
            continue  # loose file in library root — leave uncollected
        stem = os.path.splitext(os.path.basename(file))[0]
        items[v.get("ratingKey")] = (v.get("title"), rel.replace("/", " / "), stem)
    return items


def existing_collections(section):
    node = api("GET", f"/library/sections/{section}/collections")
    return {d.get("title"): d.get("ratingKey") for d in node.iter("Directory")} if node is not None else {}


def collection_members(ckey):
    node = api("GET", f"/library/collections/{ckey}/children")
    return {v.get("ratingKey") for v in node.iter("Video")} if node is not None else set()


def item_uri(machine_id, keys):
    return f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{','.join(keys)}"


def parse_timestamp(stem):
    for pat in TS_PATTERNS:
        m = pat.match(stem)
        if m:
            g = m.groupdict()
            date = f"{g['Y']}-{g['M']}-{g['D']}"
            title = f"{date} {g['h']}:{g['m']}" if "h" in g else date
            return title, date
    return None


def main():
    global TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default="Our Videos")
    ap.add_argument("--retitle", action="store_true",
                    help="rename timestamp-named items to readable dates")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    TOKEN = plex_token()
    machine_id = api("GET", "/").get("machineIdentifier")
    section, root = find_section(args.library)
    print(f"Library '{args.library}' (section {section}) rooted at {root}")

    items = library_items(section, root)
    desired = {}  # collection title -> set of ratingKeys
    for rk, (_, coll, _) in items.items():
        desired.setdefault(coll, set()).add(rk)
    print(f"{len(items)} items across {len(desired)} folders")

    have = existing_collections(section)
    for coll in sorted(desired):
        keys = desired[coll]
        if coll not in have:
            print(f"CREATE  {coll}  ({len(keys)} items)")
            if not args.dry_run:
                api("POST", "/library/collections",
                    {"type": 1, "smart": 0, "sectionId": section,
                     "title": coll, "uri": item_uri(machine_id, sorted(keys))})
        else:
            current = collection_members(have[coll])
            add, remove = keys - current, current - keys
            if add:
                print(f"ADD     {coll}  (+{len(add)} items)")
                if not args.dry_run:
                    api("PUT", f"/library/collections/{have[coll]}/items",
                        {"uri": item_uri(machine_id, sorted(add))})
            for rk in sorted(remove):
                print(f"REMOVE  {coll}  (item {rk})")
                if not args.dry_run:
                    api("DELETE", f"/library/collections/{have[coll]}/children/{rk}")

    if args.retitle:
        renamed = 0
        for rk, (title, _, stem) in items.items():
            if title != stem:
                continue  # already customized — leave alone
            parsed = parse_timestamp(stem)
            if not parsed:
                continue
            new_title, date = parsed
            print(f"RETITLE {stem}  ->  {new_title}")
            renamed += 1
            if not args.dry_run:
                api("PUT", f"/library/sections/{section}/all",
                    {"type": 1, "id": rk,
                     "title.value": new_title, "title.locked": 1,
                     "titleSort.value": new_title, "titleSort.locked": 1,
                     "originallyAvailableAt.value": date,
                     "originallyAvailableAt.locked": 1})
        print(f"{renamed} items retitled")

    print("Dry run — nothing changed." if args.dry_run else "Done.")


if __name__ == "__main__":
    main()
