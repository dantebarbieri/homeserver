"""Unattended Sonarr queue maintenance. See docker/docs/SONARR.md ("Queue maintenance").

Sonarr lists one queue row per episode, so rows are grouped by download first.
Every INTERVAL seconds, for downloads stuck for at least GRACE_MINUTES:
  - importPending/importBlocked/importFailed:
      * one file whose only rejections are episode-numbering parse failures (anime absolute
        numbers read as SxxEyy, "Invalid season or episode", "not found in the grabbed
        release") and a download grabbed for exactly one episode -> ManualImport into that
        episode (copy for torrents to keep hardlinks, move for usenet)
      * same release as the existing file, or every file rejected as "not an upgrade"
        -> blocklist + remove (Sonarr re-searches)
      * quality, language or custom-format rejections are never overridden
  - failed downloads -> blocklist + remove (Sonarr re-searches)
  - dead torrents with 0 connected seeds for 24h: below 5% (including stuck on metadata),
    or stalled with availability below 1 and no activity for 24h -> blocklist + remove
  - "not grabbed by Sonarr" queue entries -> removed from the queue (download kept)
  - MissingEpisodeSearch at most every MISSING_SEARCH_HOURS (0 disables)
Anything it can't fix is sent to ntfy once (deduplicated across runs).
"""
import os, re, json, time, traceback, unicodedata, urllib.request, urllib.error, urllib.parse, http.cookiejar
from collections import Counter

SONARR_URL = os.environ.get("SONARR_URL", "http://sonarr:8989")
SONARR_CONFIG = os.environ.get("SONARR_CONFIG", "/sonarr/config.xml")
QBIT_URL = os.environ.get("QBIT_URL", "http://qbittorrent:8080")
QBIT_USER, QBIT_PASS = os.environ.get("QBIT_USER", ""), os.environ.get("QBIT_PASS", "")
NTFY_URL, NTFY_TOPIC = os.environ.get("NTFY_URL", ""), os.environ.get("NTFY_TOPIC", "")
STATE = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "1800"))
GRACE = float(os.environ.get("GRACE_MINUTES", "20")) * 60
STALL = float(os.environ.get("STALL_HOURS", "24")) * 3600
MISSING_SEARCH_HOURS = float(os.environ.get("MISSING_SEARCH_HOURS", "168"))
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
NOT_UPGRADE = re.compile(r"not an? (custom format |quality revision )?upgrade|equal or higher", re.I)
# Rejections that only mean Sonarr couldn't map the file name to the grabbed episode.
NUMBERING = re.compile(r"not found in the grabbed release|invalid season or episode|unable to (parse|identify)"
                       r"|episode.*(was not|wasn't|not) (found|parsed)|manual import required", re.I)
HEALTHY = {"downloading", "importing", "imported"}


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"\b[0-9a-f]{32}\b", "***", msg), flush=True)


def sonarr_key():
    # Read on every call so a rotated key is picked up without a restart.
    return re.search(r"<ApiKey>([^<]+)", open(SONARR_CONFIG).read()).group(1)


def api(p, m="GET", b=None):
    r = urllib.request.Request(SONARR_URL + p, method=m, data=None if b is None else json.dumps(b).encode(),
                               headers={"X-Api-Key": sonarr_key(), "Content-Type": "application/json"})
    t = urllib.request.urlopen(r, timeout=600).read()
    return json.loads(t) if t else None


def ntfy(title, body, priority="default", tags="tv"):
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


def remove(rows):
    """Remove every queue row of one download from the client and blocklist it; Sonarr re-searches."""
    if DRY:
        return
    api("/api/v3/queue/bulk?removeFromClient=true&blocklist=true&skipRedownload=false", "DELETE",
        {"ids": [r["id"] for r in rows]})


def label(rows):
    r = rows[0]
    eps = sorted((e.get("seasonNumber", 0), e.get("episodeNumber", 0)) for e in (x.get("episode") for x in rows) if e)
    tag = (f" S{eps[0][0]:02d}E{eps[0][1]:02d}" + (f" (+{len(eps) - 1})" if len(eps) > 1 else "")) if eps else ""
    return f"{(r.get('series') or {}).get('title', '?')}{tag}"


def episode_file(eid):
    return api(f"/api/v3/episode/{eid}").get("episodeFileId") or 0


def same_as_existing(cand, eids):
    """True if the downloaded file is the release already in the library for those episodes."""
    for eid in eids:
        fid = episode_file(eid)
        if fid:
            ef = api(f"/api/v3/episodefile/{fid}")
            if cand.get("size") == ef.get("size") or stem(cand.get("path")) in {norm(ef.get("sceneName"))} - {""}:
                return True
    return False


def fix_import(rows, torrent):
    """Returns (action, None) when handled or (None, reason) when it needs the user."""
    r = rows[0]
    eids = sorted({x["episodeId"] for x in rows if x.get("episodeId")})
    try:
        cands = api("/api/v3/manualimport?" + urllib.parse.urlencode({"downloadId": r["downloadId"], "filterExistingFiles": "true"}))
    except urllib.error.HTTPError as e:
        return None, f"Sonarr could not list the download's files (HTTP {e.code})"
    cands = [c for c in cands or [] if not any(re.search(r"sample", x["reason"], re.I) for x in c.get("rejections", []))]
    if not cands:
        return None, "no importable files found in the download"
    other = {(c.get("series") or {}).get("id") for c in cands} - {None, r["seriesId"]}
    if other:
        return None, f"files match a different series (id {sorted(other)})"
    if len(cands) == 1 and same_as_existing(cands[0], eids):
        remove(rows)
        return "same release as the existing file -> blocklisted", None
    reasons = [x["reason"] for c in cands for x in c.get("rejections", [])]
    if reasons and all(NOT_UPGRADE.search(x) for x in reasons) and all(c.get("rejections") for c in cands):
        remove(rows)
        return "not an upgrade -> blocklisted", None
    c = cands[0]
    rej = [x["reason"] for x in c.get("rejections", [])]
    if len(cands) == 1 and len(eids) == 1 and rej and all(NUMBERING.search(x) for x in rej):
        if DRY:
            return f"DRY would import {os.path.basename(c['path'])} as episode {eids[0]} ({'copy' if torrent else 'move'})", None
        before = episode_file(eids[0])
        # Sonarr couldn't parse the episode from the name, so quality and languages come from the grab.
        cid = api("/api/v3/command", "POST", {"name": "ManualImport", "importMode": "copy" if torrent else "move", "files": [{
            "path": c["path"], "folderName": c.get("folderName", ""), "seriesId": r["seriesId"], "episodeIds": eids,
            "quality": r.get("quality") or c.get("quality"), "languages": r.get("languages") or c.get("languages", []),
            "releaseGroup": c.get("releaseGroup"), "indexerFlags": c.get("indexerFlags", 0),
            "releaseType": "singleEpisode", "downloadId": r["downloadId"]}]})["id"]
        for _ in range(120):
            time.sleep(5)
            if api(f"/api/v3/command/{cid}")["status"] in ("completed", "failed"):
                break
        after = episode_file(eids[0])
        if after and after != before:
            return f"imported {os.path.basename(c['path'])} (episode numbering mismatch)", None
        return None, "manual import ran but the episode file did not change"
    return None, "; ".join(dict.fromkeys(reasons))[:200] or "stuck with no rejections"


def dead(t, now):
    if t["progress"] >= 1 or t["num_seeds"] > 0 or now - t["added_on"] < STALL:
        return False
    if t["progress"] < 0.05:
        return True
    # Partly downloaded, but nobody has the missing pieces and nothing has moved for a day.
    return t.get("availability", 1) < 1 and now - (t.get("last_activity") or t["added_on"]) > STALL


def run():
    actions, needs_user = [], {}
    now = time.time()
    seen = load_state("seen.json", {})
    q = api("/api/v3/queue?pageSize=2000&includeSeries=true&includeEpisode=true&includeUnknownSeriesItems=true")["records"]
    groups = {}
    for r in q:
        groups.setdefault(r.get("downloadId") or str(r["id"]), []).append(r)
    log("queue", len(q), "rows,", len(groups), "downloads",
        dict(Counter(f"{rs[0].get('trackedDownloadState')}/{rs[0].get('trackedDownloadStatus')}" for rs in groups.values())))
    stuck = set()
    for did, rows in groups.items():
        r = rows[0]
        state, status = r.get("trackedDownloadState"), r.get("trackedDownloadStatus")
        if r.get("status") == "delay" or (state in HEALTHY and status == "ok"):
            continue
        stuck.add(did)
        # Give Sonarr's own import/failure handling a chance before stepping in.
        if now - seen.setdefault(did, now) < GRACE:
            continue
        name = label(rows)
        msgs = "; ".join(m for s in r.get("statusMessages", []) for m in [s.get("title", "")] + s.get("messages", []))
        try:
            if not r.get("seriesId") and re.search(r"(wasn't|was not|not) grabbed", msgs, re.I):
                if not DRY:
                    api(f"/api/v3/queue/{r['id']}?removeFromClient=false&blocklist=false", "DELETE")
                actions.append(f"removed stale: {r['title'][:60]}")
            elif state in ("failedPending", "failed"):
                remove(rows)
                actions.append(f"failed -> blocklisted: {name}")
            elif state in ("importFailed", "importPending", "importBlocked") and r.get("seriesId"):
                done, why = fix_import(rows, r.get("protocol") == "torrent")
                if done:
                    actions.append(f"{name}: {done}")
                else:
                    needs_user[f"import:{did}"] = f"{name}: {why} | {r['title'][:80]}"
            # Torrent warnings ("stalled", "no connections") are left to the dead-torrent rule below.
            elif status in ("warning", "error") and r.get("protocol") != "torrent":
                needs_user[f"warn:{did}"] = f"{name}: {state}/{status} {msgs[:150]}"
        except Exception as e:
            needs_user[f"err:{did}"] = f"{name}: {type(e).__name__}: {e}"[:200]

    if QBIT_USER:
        cats = {f.get("value") for c in api("/api/v3/downloadclient") if c["implementation"] == "QBittorrent"
                for f in c["fields"] if f["name"] == "tvCategory"} - {None, ""}
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = op.open(f"{QBIT_URL}/api/v2/auth/login", urllib.parse.urlencode({"username": QBIT_USER, "password": QBIT_PASS}).encode(), timeout=30).read()
        if login.strip() == b"Fails.":
            raise RuntimeError("qBittorrent login failed (check QBIT_USER/QBIT_PASS)")
        byhash = {k.lower(): v for k, v in groups.items()}
        for cat in sorted(cats):
            for t in json.loads(op.open(f"{QBIT_URL}/api/v2/torrents/info?" + urllib.parse.urlencode({"category": cat}), timeout=60).read()):
                if not dead(t, now):
                    continue
                rows = byhash.get(t["hash"].lower())
                if rows:
                    remove(rows)
                    actions.append(f"dead torrent ({t['state']}, {t['progress']:.0%}) -> blocklisted: {t['name'][:60]}")
                else:
                    needs_user[f"stalled:{t['hash']}"] = f"dead torrent not tracked by Sonarr: {t['name'][:80]}"

    if MISSING_SEARCH_HOURS > 0:
        cutoff = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - MISSING_SEARCH_HOURS * 3600))
        recent = now - load_state("last_missing.json", {}).get("at", 0) < MISSING_SEARCH_HOURS * 3600
        recent = recent or any(c["name"] == "MissingEpisodeSearch" and (c.get("started") or c.get("queued") or "") >= cutoff
                               for c in api("/api/v3/command"))
        if not recent and not DRY:
            api("/api/v3/command", "POST", {"name": "MissingEpisodeSearch", "monitored": True})
            save_state("last_missing.json", {"at": now})
            actions.append("triggered MissingEpisodeSearch")

    for a in actions:
        log("ACTION:", a)
    for v in needs_user.values():
        log("NEEDS USER:", v)
    save_state("seen.json", {k: v for k, v in seen.items() if k in stuck})

    notified = load_state("notified.json", {})
    new = [v for k, v in needs_user.items() if k not in notified]
    if new and not DRY:
        ntfy("Sonarr: needs attention", "\n".join(new), "default", "tv,warning")
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
                    ntfy("Sonarr maintenance: run failed", msg, "high", "tv,rotating_light")
                save_state("last_error.json", {"msg": msg, "at": time.time()})
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
