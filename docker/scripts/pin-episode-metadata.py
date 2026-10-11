#!/usr/bin/env python3
"""Pin per-episode metadata for a show whose files use a custom episode order.

Plex and Jellyfin map files to episodes by the SxxExx in the filename, then
pull titles/summaries/thumbnails for that slot from an upstream order
(TheTVDB aired/DVD, TMDB, ...). When a show's files are deliberately numbered
in an order that no upstream source offers anymore (e.g. Kim Possible's old
chronological TVDB "DVD order", rewritten upstream in 2026), the playback
order is still right but every label is wrong.

This script makes the files the source of truth. An order file maps each
on-disk SxxExx to a TheTVDB *episode ID* (stable across order edits); the
script fetches that episode's title, air date, overview and image from
TheTVDB and then:

  * Jellyfin: writes `<video>.nfo` (with <lockdata>) and `<video>-thumb.jpg`
    next to each file, then refreshes the series so the NFOs are read.
  * Plex: sets title/summary/air date/thumbnail on each episode and
    locks those fields so Plex metadata refreshes cannot undo them.

Idempotent: re-running only touches items that differ. The fetched TVDB data
is cached in `<show>/.pinned-episode-metadata.json` and used as a fallback if
TheTVDB is unreachable.

Run on the server (no system python — use nix-shell):
    nix-shell -p python3 --run \\
        '/srv/homeserver/docker/scripts/pin-episode-metadata.py \\
         /srv/homeserver/docker/scripts/episode-orders/kim-possible.json [--dry-run]'

Credentials: the Plex token is read from the plex container's Preferences.xml
(override with PLEX_TOKEN); the Jellyfin API key from JELLYFIN_API_KEY or
HOMEPAGE_VAR_JELLYFIN_KEY in /srv/homeserver/docker/.env. Plex is reached at
PLEX_URL (default http://127.0.0.1:32400); Jellyfin at JELLYFIN_URL (default:
the jellyfin container's IP on port 8096).
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".wmv", ".webm"}
EP_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
ENV_FILE = "/srv/homeserver/docker/.env"
UA = {"User-Agent": "Mozilla/5.0 (pin-episode-metadata)"}
CACHE_NAME = ".pinned-episode-metadata.json"


# ── TheTVDB ──────────────────────────────────────────────────────────

def fetch(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_date(text):
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def tvdb_episodes(slug):
    """Scrape every episode of a series from its TheTVDB all-seasons page.
    -> {episode_id: {title, aired, overview, image}}"""
    page = fetch(f"https://thetvdb.com/series/{slug}/allseasons/official").decode()
    eps = {}
    for chunk in page.split('<li class="list-group-item')[1:]:
        m = re.search(r'episode-label">[^<]*</\w+>\s*<a href="/series/[^/]+/episodes/(\d+)">(.*?)</a>',
                      chunk, re.S)
        if not m:
            continue
        info = {"title": clean(m.group(2)), "aired": None, "overview": "", "image": None}
        d = re.search(r'<ul class="list-inline text-muted">\s*<li>([^<]+)</li>', chunk)
        if d:
            info["aired"] = parse_date(d.group(1))
        o = re.search(r'<div class="col-xs-9">\s*<p>(.*?)</p>', chunk, re.S)
        if o:
            info["overview"] = clean(o.group(1))
        i = re.search(r'data-src="(https://artworks\.thetvdb\.com/[^"]+)"', chunk)
        if i:
            info["image"] = i.group(1)
        eps[int(m.group(1))] = info
    if not eps:
        raise RuntimeError("no episodes parsed — TheTVDB page layout changed?")
    return eps


def load_metadata(order, show_dir, dry_run):
    cache = show_dir / CACHE_NAME
    wanted = set(order["episodes"].values())
    try:
        eps = tvdb_episodes(order["tvdb"]["slug"])
        missing = wanted - set(eps)
        if missing:
            raise RuntimeError(f"TheTVDB page lacks episode IDs {sorted(missing)}")
        data = {str(k): v for k, v in eps.items() if k in wanted}
        if not dry_run:
            cache.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        return {int(k): v for k, v in data.items()}
    except Exception as e:  # noqa: BLE001 — any fetch/parse failure → cache
        if not cache.exists():
            sys.exit(f"TheTVDB fetch failed ({e}) and no cache at {cache}")
        print(f"WARNING: TheTVDB fetch failed ({e}); using cached {cache.name}")
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}


# ── Files ────────────────────────────────────────────────────────────

def episode_files(show_dir, order):
    """-> list of (path, season, episode, tvdb_id) for mapped video files."""
    out, unmapped = [], []
    for path in sorted(show_dir.rglob("*")):
        if path.suffix.lower() not in VIDEO_EXTS or path.name.startswith("."):
            continue
        m = EP_RE.search(path.name)
        if not m:
            continue
        s, e = int(m.group(1)), int(m.group(2))
        tvdb_id = order["episodes"].get(f"S{s:02d}E{e:02d}")
        if tvdb_id is None:
            unmapped.append(path.name)
        else:
            out.append((path, s, e, tvdb_id))
    for name in unmapped:
        print(f"WARNING: no mapping for {name} — left untouched")
    return out


def nfo_xml(show_title, s, e, tvdb_id, meta):
    rows = [
        ("title", meta["title"]),
        ("showtitle", show_title),
        ("season", str(s)),
        ("episode", str(e)),
        ("plot", meta["overview"]),
    ]
    if meta["aired"]:
        rows += [("aired", meta["aired"]), ("premiered", meta["aired"])]
    body = "\n".join(f"  <{k}>{escape(v)}</{k}>" for k, v in rows)
    return ('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
            "<episodedetails>\n"
            f"{body}\n"
            f'  <uniqueid type="tvdb" default="true">{tvdb_id}</uniqueid>\n'
            "  <lockdata>true</lockdata>\n"
            "</episodedetails>\n")


def write_sidecars(files, metadata, show_title, dry_run, refresh_images):
    """Write Jellyfin NFO + thumb sidecars. Returns number of changed files."""
    changed = 0
    for path, s, e, tvdb_id in files:
        meta = metadata[tvdb_id]
        nfo = path.with_suffix(".nfo")
        want = nfo_xml(show_title, s, e, tvdb_id, meta)
        if not nfo.exists() or nfo.read_text(encoding="utf-8") != want:
            print(f"NFO     S{s:02d}E{e:02d}  {meta['title']}")
            changed += 1
            if not dry_run:
                nfo.write_text(want, encoding="utf-8")
        thumb = path.with_name(path.stem + "-thumb.jpg")
        if meta["image"] and (refresh_images or not thumb.exists()):
            print(f"THUMB   S{s:02d}E{e:02d}  {meta['image']}")
            changed += 1
            if not dry_run:
                thumb.write_bytes(fetch(meta["image"]))
    return changed


# ── Jellyfin ─────────────────────────────────────────────────────────

def env_file_value(key):
    try:
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def jellyfin_conn():
    key = os.environ.get("JELLYFIN_API_KEY") or env_file_value("HOMEPAGE_VAR_JELLYFIN_KEY")
    url = os.environ.get("JELLYFIN_URL")
    if not url:
        ip = subprocess.run(
            ["docker", "inspect", "jellyfin", "--format",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"],
            capture_output=True, text=True, check=True).stdout.split()
        url = f"http://{ip[0]}:8096" if ip else None
    if not key or not url:
        sys.exit("Jellyfin URL/API key not found; set JELLYFIN_URL and JELLYFIN_API_KEY")
    return url, key


def jellyfin_refresh(show_dir, title, dry_run):
    url, key = jellyfin_conn()
    hdr = {"Authorization": f'MediaBrowser Token="{key}"'}
    q = urllib.parse.urlencode({"IncludeItemTypes": "Series", "Recursive": "true",
                                "searchTerm": title, "Fields": "Path"})
    items = json.loads(fetch(f"{url}/Items?{q}", hdr))["Items"]
    series = [i for i in items if i.get("Path", "").rstrip("/").endswith("/" + show_dir.name)]
    if not series:
        print(f"WARNING: Jellyfin series for '{show_dir.name}' not found — skipped refresh")
        return
    sid = series[0]["Id"]
    print(f"JELLYFIN refresh series {sid} (replace all metadata + images)")
    if not dry_run:
        q = urllib.parse.urlencode({"Recursive": "true", "MetadataRefreshMode": "FullRefresh",
                                    "ImageRefreshMode": "FullRefresh",
                                    "ReplaceAllMetadata": "true", "ReplaceAllImages": "true"})
        fetch(f"{url}/Items/{sid}/Refresh?{q}", hdr, data=b"", method="POST")


# ── Plex ─────────────────────────────────────────────────────────────

PLEX_URL = os.environ.get("PLEX_URL", "http://127.0.0.1:32400")
PLEX_TOKEN = None


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


def plex(method, path, params=None):
    params = {**(params or {}), "X-Plex-Token": PLEX_TOKEN}
    body = fetch(f"{PLEX_URL}{path}?{urllib.parse.urlencode(params)}",
                 {"X-Plex-Container-Size": "10000"}, method=method)
    return ET.fromstring(body) if body.strip() else None


def plex_episodes(show_dir, title):
    """-> (section_id, {file basename: ratingKey}) for the show in show_dir."""
    for d in plex("GET", "/library/sections").iter("Directory"):
        if d.get("type") != "show":
            continue
        for show in plex("GET", f"/library/sections/{d.get('key')}/all",
                         {"type": 2, "title": title}).iter("Directory"):
            leaves = {}
            for v in plex("GET", f"/library/metadata/{show.get('ratingKey')}/allLeaves").iter("Video"):
                part = v.find("./Media/Part")
                if part is not None and f"/{show_dir.name}/" in part.get("file", ""):
                    leaves[os.path.basename(part.get("file"))] = v.get("ratingKey")
            if leaves:
                return d.get("key"), leaves
    return None, {}


def plex_pin(files, metadata, show_dir, title, dry_run, refresh_images=False):
    global PLEX_TOKEN
    PLEX_TOKEN = plex_token()
    section, leaves = plex_episodes(show_dir, title)
    if not leaves:
        print(f"WARNING: Plex show for '{show_dir.name}' not found — skipped")
        return
    changed = 0
    for path, s, e, tvdb_id in files:
        rk = leaves.get(path.name)
        if rk is None:
            print(f"WARNING: Plex has no item for {path.name}")
            continue
        meta = metadata[tvdb_id]
        item = plex("GET", f"/library/metadata/{rk}").find("Video")
        locked = {f.get("name") for f in item.iter("Field") if f.get("locked") == "1"}
        want = {"title": meta["title"], "summary": meta["overview"]}
        if meta["aired"]:
            want["originallyAvailableAt"] = meta["aired"]
        diff = {k: v for k, v in want.items()
                if (item.get(k) or "") != v or k not in locked}
        if diff:
            print(f"PLEX    S{s:02d}E{e:02d}  {item.get('title')!r} -> {meta['title']!r}"
                  f"  [{', '.join(sorted(diff))}]")
            changed += 1
            if not dry_run:
                params = {"type": 4, "id": rk}
                for k, v in diff.items():
                    params[f"{k}.value"] = v
                    params[f"{k}.locked"] = 1
                plex("PUT", f"/library/sections/{section}/all", params)
        if meta["image"]:
            posters = plex("GET", f"/library/metadata/{rk}/posters")
            selected = [p.get("ratingKey") for p in posters.iter("Photo") if p.get("selected") == "1"]
            # Plex stores URL-posted posters as upload://…, so a locked thumb with
            # an uploaded poster selected is treated as already pinned.
            pinned = "thumb" in locked and any(
                k == meta["image"] or (k or "").startswith("upload://") for k in selected)
            if refresh_images or not pinned:
                print(f"PLEX    S{s:02d}E{e:02d}  thumb -> {meta['image']}")
                changed += 1
                if not dry_run:
                    plex("POST", f"/library/metadata/{rk}/posters", {"url": meta["image"]})
                    plex("PUT", f"/library/sections/{section}/all",
                         {"type": 4, "id": rk, "thumb.locked": 1})
    print(f"Plex: {changed} change(s)")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("order", type=Path, help="episode order JSON (see episode-orders/)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-plex", action="store_true")
    ap.add_argument("--no-jellyfin", action="store_true")
    ap.add_argument("--refresh-images", action="store_true",
                    help="re-download/re-upload thumbnails even if already pinned")
    ap.add_argument("--force-jellyfin-refresh", action="store_true",
                    help="refresh the Jellyfin series even if no sidecar changed")
    args = ap.parse_args()

    order = json.loads(args.order.read_text())
    show_dir = Path(order["path"])
    if not show_dir.is_dir():
        sys.exit(f"Show folder not found: {show_dir}")
    title = order["title"]

    metadata = load_metadata(order, show_dir, args.dry_run)
    files = episode_files(show_dir, order)
    print(f"{title}: {len(files)} mapped files, {len(metadata)} TVDB episodes")

    if not args.no_jellyfin:
        changed = write_sidecars(files, metadata, title, args.dry_run, args.refresh_images)
        print(f"Jellyfin sidecars: {changed} change(s)")
        if changed or args.force_jellyfin_refresh:
            jellyfin_refresh(show_dir, title, args.dry_run)
    if not args.no_plex:
        plex_pin(files, metadata, show_dir, title, args.dry_run, args.refresh_images)

    print("Dry run — nothing changed." if args.dry_run else "Done.")


if __name__ == "__main__":
    main()
