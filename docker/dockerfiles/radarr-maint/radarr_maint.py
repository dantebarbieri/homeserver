"""Unattended Radarr queue maintenance. See docker/docs/RADARR.md ("Queue maintenance").

Every INTERVAL seconds, for queue items stuck for at least GRACE_MINUTES:
  - importPending/importBlocked/importFailed:
      * exactly one importable file (Radarr reports no rejections), e.g. "matched by ID,
        Manual Import required" -> ManualImport into the queued movie (copy for torrents
        to keep hardlinks, move for usenet)
      * same release as the existing file, or every file rejected as "not an upgrade"
        (e.g. an AI upscale caught by a negative custom format) -> blocklist + remove
  - failed downloads -> blocklist + remove (Radarr re-searches)
  - torrents stalled at <5% with 0 seeds for 24h -> blocklist + remove
  - "not grabbed by Radarr" queue entries -> removed from the queue (download kept)
  - MissingMoviesSearch at most every MISSING_SEARCH_HOURS
Anything it can't fix is sent to ntfy once (deduplicated across runs).
"""
import os, re, json, time, traceback, unicodedata, urllib.request, urllib.parse, http.cookiejar
from collections import Counter

RADARR_URL = os.environ.get("RADARR_URL", "http://radarr:7878")
RADARR_CONFIG = os.environ.get("RADARR_CONFIG", "/radarr/config.xml")
QBIT_URL = os.environ.get("QBIT_URL", "http://qbittorrent:8080")
QBIT_USER, QBIT_PASS = os.environ.get("QBIT_USER", ""), os.environ.get("QBIT_PASS", "")
NTFY_URL, NTFY_TOPIC = os.environ.get("NTFY_URL", ""), os.environ.get("NTFY_TOPIC", "")
STATE = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "1800"))
GRACE = float(os.environ.get("GRACE_MINUTES", "20")) * 60
MISSING_SEARCH_HOURS = float(os.environ.get("MISSING_SEARCH_HOURS", "24"))
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
NOT_UPGRADE = re.compile(r"not an? (custom format |quality revision )?upgrade|equal or higher", re.I)
HEALTHY = {"downloading", "importing", "imported"}


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"\b[0-9a-f]{32}\b", "***", msg), flush=True)


def radarr_key():
    # Read on every call so a rotated key is picked up without a restart.
    return re.search(r"<ApiKey>([^<]+)", open(RADARR_CONFIG).read()).group(1)


def api(p, m="GET", b=None):
    r = urllib.request.Request(RADARR_URL + p, method=m, data=None if b is None else json.dumps(b).encode(),
                               headers={"X-Api-Key": radarr_key(), "Content-Type": "application/json"})
    t = urllib.request.urlopen(r, timeout=600).read()
    return json.loads(t) if t else None


def ntfy(title, body, priority="default", tags="movie_camera"):
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
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "").lower()))


def stem(path):
    return norm(os.path.splitext(os.path.basename(path or ""))[0])


def remove(r):
    """Remove from the client and blocklist; Radarr then searches for another release."""
    if DRY:
        return
    api(f"/api/v3/queue/{r['id']}?removeFromClient=true&blocklist=true&skipRedownload=false", "DELETE")


def same_as_existing(cand, mf):
    """True if the downloaded file is the release already in the library."""
    if not mf:
        return False
    names = {norm(mf.get("sceneName")), stem(mf.get("originalFilePath"))} - {""}
    return cand.get("size") == mf.get("size") or stem(cand.get("path")) in names


def fix_import(r, torrent):
    """Returns (action, None) when handled or (None, reason) when it needs the user."""
    mf = api(f"/api/v3/movie/{r['movieId']}").get("movieFile")
    cands = api("/api/v3/manualimport?" + urllib.parse.urlencode({"downloadId": r["downloadId"], "filterExistingFiles": "true"}))
    if not cands:
        return None, "no importable files found in the download"
    other = {(c.get("movie") or {}).get("id") for c in cands} - {None, r["movieId"]}
    if other:
        return None, f"files match a different movie (id {sorted(other)})"
    if any(same_as_existing(c, mf) for c in cands):
        remove(r)
        return "same release as the existing file -> blocklisted", None
    ok = [c for c in cands if not c.get("rejections")]
    if len(ok) == 1:
        c = ok[0]
        if DRY:
            return f"DRY would import {os.path.basename(c['path'])} ({'copy' if torrent else 'move'})", None
        before = (mf or {}).get("id")
        cid = api("/api/v3/command", "POST", {"name": "ManualImport", "importMode": "copy" if torrent else "move", "files": [{
            "path": c["path"], "movieId": r["movieId"], "quality": c["quality"], "languages": c.get("languages", []),
            "releaseGroup": c.get("releaseGroup"), "indexerFlags": c.get("indexerFlags", 0), "downloadId": r["downloadId"]}]})["id"]
        for _ in range(120):
            time.sleep(5)
            if api(f"/api/v3/command/{cid}")["status"] in ("completed", "failed"):
                break
        after = (api(f"/api/v3/movie/{r['movieId']}").get("movieFile") or {}).get("id")
        if after and after != before:
            return f"imported {os.path.basename(c['path'])}", None
        return None, "manual import ran but the movie file did not change"
    reasons = [x["reason"] for c in cands for x in c.get("rejections", [])]
    if not ok and reasons and all(NOT_UPGRADE.search(x) for x in reasons):
        remove(r)
        return "not an upgrade -> blocklisted", None
    if len(ok) > 1:
        return None, f"{len(ok)} importable files, ambiguous"
    return None, "; ".join(dict.fromkeys(reasons))[:200] or "unknown import problem"


def run():
    actions, needs_user = [], {}
    now = time.time()
    seen = load_state("seen.json", {})
    q = api("/api/v3/queue?pageSize=1000&includeMovie=true&includeUnknownMovieItems=true")["records"]
    log("queue", len(q), dict(Counter(f"{r.get('trackedDownloadState')}/{r.get('trackedDownloadStatus')}" for r in q)))
    stuck = set()
    for r in q:
        state, status = r.get("trackedDownloadState"), r.get("trackedDownloadStatus")
        if state in HEALTHY and status == "ok":
            continue
        did = r.get("downloadId") or str(r["id"])
        stuck.add(did)
        # Give Radarr's own import/failure handling a chance before stepping in.
        if now - seen.setdefault(did, now) < GRACE:
            continue
        movie = r.get("movie") or {}
        name = f"{movie.get('title', '?')} ({movie.get('year', '')})"
        msgs = "; ".join(m for s in r.get("statusMessages", []) for m in [s.get("title", "")] + s.get("messages", []))
        try:
            if not r.get("movieId") and re.search(r"(wasn't|was not|not) grabbed", msgs, re.I):
                if not DRY:
                    api(f"/api/v3/queue/{r['id']}?removeFromClient=false&blocklist=false", "DELETE")
                actions.append(f"removed stale: {r['title'][:60]}")
            elif state in ("failedPending", "failed"):
                remove(r)
                actions.append(f"failed -> blocklisted: {name}")
            elif state in ("importFailed", "importPending", "importBlocked") and r.get("movieId"):
                done, why = fix_import(r, r.get("protocol") == "torrent")
                if done:
                    actions.append(f"{name}: {done}")
                else:
                    needs_user[f"import:{did}"] = f"{name}: {why} | {r['title'][:80]}"
            elif status in ("warning", "error"):
                needs_user[f"warn:{did}"] = f"{name}: {state}/{status} {msgs[:150]}"
        except Exception as e:
            needs_user[f"err:{did}"] = f"{name}: {type(e).__name__}: {e}"[:200]

    if QBIT_USER:
        cats = {f.get("value") for c in api("/api/v3/downloadclient") if c["implementation"] == "QBittorrent"
                for f in c["fields"] if f["name"] == "movieCategory"} - {None, ""}
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = op.open(f"{QBIT_URL}/api/v2/auth/login", urllib.parse.urlencode({"username": QBIT_USER, "password": QBIT_PASS}).encode(), timeout=30).read()
        if login.strip() == b"Fails.":
            raise RuntimeError("qBittorrent login failed (check QBIT_USER/QBIT_PASS)")
        byhash = {(r.get("downloadId") or "").lower(): r for r in q}
        for cat in sorted(cats):
            for t in json.loads(op.open(f"{QBIT_URL}/api/v2/torrents/info?" + urllib.parse.urlencode({"category": cat}), timeout=60).read()):
                if t["progress"] < 0.05 and t["num_seeds"] == 0 and now - t["added_on"] > 86400:
                    r = byhash.get(t["hash"].lower())
                    if r:
                        remove(r)
                        actions.append(f"stalled torrent -> blocklisted: {t['name'][:60]}")
                    else:
                        needs_user[f"stalled:{t['hash']}"] = f"stalled torrent not tracked by Radarr: {t['name'][:80]}"

    cutoff = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - MISSING_SEARCH_HOURS * 3600))
    recent = now - load_state("last_missing.json", {}).get("at", 0) < MISSING_SEARCH_HOURS * 3600
    recent = recent or any(c["name"] == "MissingMoviesSearch" and (c.get("started") or c.get("queued") or "") >= cutoff
                           for c in api("/api/v3/command"))
    if not recent and not DRY:
        api("/api/v3/command", "POST", {"name": "MissingMoviesSearch", "filterKey": "monitored", "filterValue": "true"})
        save_state("last_missing.json", {"at": now})
        actions.append("triggered MissingMoviesSearch")

    for a in actions:
        log("ACTION:", a)
    for v in needs_user.values():
        log("NEEDS USER:", v)
    save_state("seen.json", {k: v for k, v in seen.items() if k in stuck})

    notified = load_state("notified.json", {})
    new = [v for k, v in needs_user.items() if k not in notified]
    if new and not DRY:
        ntfy("Radarr: needs attention", "\n".join(new), "default", "movie_camera,warning")
    save_state("notified.json", {k: notified.get(k, now) for k in needs_user})


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
                    ntfy("Radarr maintenance: run failed", msg, "high", "movie_camera,rotating_light")
                save_state("last_error.json", {"msg": msg, "at": time.time()})
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
