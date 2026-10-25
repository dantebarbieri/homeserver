"""Unattended Lidarr queue maintenance. See docker/docs/MUSIC.md ("Queue maintenance").

Every INTERVAL seconds:
  - imports importFailed/Pending/Blocked downloads whose file count matches another
    edition of the album and whose titles match (copy for torrents to keep hardlinks,
    move for usenet); never switches editions on an album that already has files
  - blocklists + re-searches failed downloads, wrong tiny releases (<=4 files for an
    8+ track album) and torrents stalled at <5% with 0 seeds for 24h
  - removes stale "not grabbed" queue entries
  - triggers MissingAlbumSearch at most every MISSING_SEARCH_HOURS
Anything it can't fix is sent to ntfy once (deduplicated across runs).
"""
import os, re, json, time, difflib, unicodedata, traceback, urllib.request, urllib.parse, http.cookiejar
from collections import Counter

LIDARR_URL = os.environ.get("LIDARR_URL", "http://lidarr:8686")
LIDARR_CONFIG = os.environ.get("LIDARR_CONFIG", "/lidarr/config.xml")
QBIT_URL = os.environ.get("QBIT_URL", "http://qbittorrent:8080")
QBIT_USER, QBIT_PASS = os.environ.get("QBIT_USER", ""), os.environ.get("QBIT_PASS", "")
QBIT_CATEGORY = os.environ.get("QBIT_CATEGORY", "music")
NTFY_URL, NTFY_TOPIC = os.environ.get("NTFY_URL", ""), os.environ.get("NTFY_TOPIC", "")
STATE = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "1800"))
MISSING_SEARCH_HOURS = float(os.environ.get("MISSING_SEARCH_HOURS", "6"))
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
AUD = (".flac", ".m4a", ".mp3", ".ape", ".wv")


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"\b[0-9a-f]{32}\b", "***", msg), flush=True)


def lidarr_key():
    # Read on every call so a rotated key is picked up without a restart.
    return re.search(r"<ApiKey>([^<]+)", open(LIDARR_CONFIG).read()).group(1)


def api(p, m="GET", b=None):
    r = urllib.request.Request(LIDARR_URL + p, method=m, data=None if b is None else json.dumps(b).encode(),
                               headers={"X-Api-Key": lidarr_key(), "Content-Type": "application/json"})
    t = urllib.request.urlopen(r, timeout=600).read()
    return json.loads(t) if t else None


def ntfy(title, body, priority="default", tags="musical_note"):
    if not (NTFY_URL and NTFY_TOPIC):
        return
    try:
        req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}", data=body.encode(),
                                     headers={"Title": title, "Priority": priority, "Tags": tags})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log("WARNING: ntfy send failed:", e)


def load_state(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_state(name, value):
    if DRY:
        return
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(value, f)
    os.replace(tmp, os.path.join(STATE, name))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s.lower()))


def strip(fname):
    return re.sub(r"^[\d\s.\-_]+", "", os.path.splitext(fname)[0])


def audio_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs if f.lower().endswith(AUD))


def import_dir(folder, album_id, mode, download_id=None, min_score=0.45):
    if not os.path.isdir(folder):
        return "no folder"
    files = audio_files(folder)
    alb = api(f"/api/v1/album/{album_id}")
    best = None
    for rel in [r for r in alb["releases"] if r["trackCount"] == len(files)]:
        tr = sorted(api(f"/api/v1/track?albumReleaseId={rel['id']}"), key=lambda t: (t["mediumNumber"], t["absoluteTrackNumber"]))
        sc = sum(difflib.SequenceMatcher(None, norm(t["title"]), norm(strip(os.path.basename(f)))).ratio() for f, t in zip(files, tr)) / len(files)
        if not best or sc > best[0]:
            best = (sc, rel, tr)
    if not best:
        return f"{len(files)} files, no release with that count ({sorted({r['trackCount'] for r in alb['releases']})})"
    sc, rel, tr = best
    if sc < min_score:
        return f"low title match {sc:.2f}"
    if DRY:
        return f"DRY would import {len(files)} into {rel['format']} score {sc:.2f}"
    if not rel["monitored"]:
        # Switching the monitored edition unlinks files already imported on another edition.
        if (alb.get("statistics") or {}).get("trackFileCount"):
            return f"album already has {alb['statistics']['trackFileCount']} files on another release; not switching"
        for r in alb["releases"]:
            r["monitored"] = r["id"] == rel["id"]
        api(f"/api/v1/album/{album_id}", "PUT", alb)
    q = {i["path"]: i for i in api("/api/v1/manualimport?" + urllib.parse.urlencode({"folder": folder, "filterExistingFiles": "false"}))}
    payload = [dict({"path": f, "artistId": alb["artistId"], "albumId": album_id, "albumReleaseId": rel["id"], "trackIds": [t["id"]],
                     "quality": q[f]["quality"], "disableReleaseSwitching": True, "indexerFlags": 0},
                    **({"downloadId": download_id} if download_id else {})) for f, t in zip(files, tr)]
    cid = api("/api/v1/command", "POST", {"name": "ManualImport", "files": payload, "importMode": mode, "replaceExistingFiles": False})["id"]
    for _ in range(60):
        time.sleep(5)
        if api(f"/api/v1/command/{cid}")["status"] in ("completed", "failed"):
            break
    s = api(f"/api/v1/album/{album_id}")["statistics"]
    return f"imported {s['trackFileCount']}/{s['trackCount']} (score {sc:.2f})" if s["trackFileCount"] else "import ran but 0 files"


def remove_and_research(r):
    if DRY:
        return
    api(f"/api/v1/queue/{r['id']}?removeFromClient=true&blocklist=true", "DELETE")
    api("/api/v1/command", "POST", {"name": "AlbumSearch", "albumIds": [r["albumId"]]})


def run():
    actions, needs_user = [], {}
    q = api("/api/v1/queue?pageSize=500&includeArtist=true&includeAlbum=true")["records"]
    log("queue", len(q), dict(Counter(f"{r.get('trackedDownloadState')}/{r.get('trackedDownloadStatus')}" for r in q)))
    for r in q:
        state, status = r.get("trackedDownloadState"), r.get("trackedDownloadStatus")
        name = f"{(r.get('artist') or {}).get('artistName')} - {(r.get('album') or {}).get('title', '')[:50]}"
        msgs = "; ".join(m for s in r.get("statusMessages", []) for m in [s.get("title", "")] + s.get("messages", []))
        torrent = r.get("protocol") == "torrent" or (r.get("downloadClient") or "").startswith("qBit")
        if state == "downloading" and status == "ok":
            continue
        if "wasn't grabbed by Lidarr" in msgs or "not grabbed" in msgs:
            if not DRY:
                api(f"/api/v1/queue/{r['id']}?removeFromClient=false&blocklist=false", "DELETE")
            actions.append(f"removed stale: {r['title'][:60]}")
            continue
        if state in ("failedPending", "failed") or r.get("status") in ("failed", "warning") and state == "downloading" and status == "error":
            remove_and_research(r)
            actions.append(f"failed -> blocklisted+re-search: {name}")
            continue
        if state in ("importFailed", "importPending", "importBlocked"):
            nfiles = len(audio_files(r.get("outputPath")))
            counts = {x["trackCount"] for x in api(f"/api/v1/album/{r['albumId']}")["releases"]}
            if nfiles and nfiles <= 4 and counts and min(counts) >= 8:
                remove_and_research(r)
                actions.append(f"wrong release ({nfiles} files) -> blocklisted+re-search: {name}")
                continue
            res = import_dir(r.get("outputPath") or "", r["albumId"], "copy" if torrent else "move", r["downloadId"])
            if res.startswith(("imported", "DRY")):
                actions.append(f"{name}: {res}")
            else:
                needs_user[f"import:{r['downloadId']}"] = f"{name}: {res} | {r['title'][:80]}"
            continue
        if torrent and status in ("warning", "error"):
            needs_user[f"warn:{r['downloadId']}"] = f"{name}: {state}/{status} {msgs[:150]}"

    if QBIT_USER:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.open(f"{QBIT_URL}/api/v2/auth/login", urllib.parse.urlencode({"username": QBIT_USER, "password": QBIT_PASS}).encode(), timeout=30)
        byhash = {(r.get("downloadId") or "").lower(): r for r in q}
        for t in json.loads(op.open(f"{QBIT_URL}/api/v2/torrents/info?category={QBIT_CATEGORY}", timeout=60).read()):
            if t["progress"] < 0.05 and t["num_seeds"] == 0 and time.time() - t["added_on"] > 86400:
                r = byhash.get(t["hash"].lower())
                if r:
                    remove_and_research(r)
                    actions.append(f"stalled torrent blocklisted+re-search: {t['name'][:60]}")
                else:
                    needs_user[f"stalled:{t['hash']}"] = f"stalled torrent not tracked by Lidarr: {t['name'][:80]}"

    cutoff = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - MISSING_SEARCH_HOURS * 3600))
    recent = time.time() - load_state("last_missing.json", {}).get("at", 0) < MISSING_SEARCH_HOURS * 3600
    recent = recent or any(c["name"] == "MissingAlbumSearch" and (c.get("started") or c.get("queued") or "") >= cutoff
                           for c in api("/api/v1/command"))
    if not recent and not DRY:
        api("/api/v1/command", "POST", {"name": "MissingAlbumSearch"})
        save_state("last_missing.json", {"at": time.time()})
        actions.append("triggered MissingAlbumSearch")

    albums = api("/api/v1/album")
    st = lambda a: a.get("statistics") or {}
    mon = [a for a in albums if a["monitored"]]
    complete = sum(1 for a in mon if st(a).get("trackCount") and st(a).get("trackFileCount", 0) >= st(a)["trackCount"])
    for a in actions:
        log("ACTION:", a)
    for v in needs_user.values():
        log("NEEDS USER:", v)
    log(f"library: complete {complete}/{len(mon)} | tracks {sum(st(a).get('trackFileCount', 0) for a in albums)}")

    notified = load_state("notified.json", {})
    new = [v for k, v in needs_user.items() if k not in notified]
    if new and not DRY:
        ntfy("Lidarr: needs attention", "\n".join(new), "default", "musical_note,warning")
    save_state("notified.json", {k: notified.get(k, time.time()) for k in needs_user})


def main():
    os.makedirs(STATE, exist_ok=True)
    while True:
        try:
            run()
            save_state("last_ok.json", {"at": time.time()})
        except Exception as e:
            log("ERROR:", traceback.format_exc())
            err = load_state("last_error.json", {})
            msg = f"{type(e).__name__}: {e}"[:300]
            if err.get("msg") != msg or time.time() - err.get("at", 0) > 6 * 3600:
                if not DRY:
                    ntfy("Lidarr maintenance: run failed", msg, "high", "musical_note,rotating_light")
                save_state("last_error.json", {"msg": msg, "at": time.time()})
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
