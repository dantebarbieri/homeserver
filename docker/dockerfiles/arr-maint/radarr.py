"""Radarr rules. See docker/docs/RADARR.md ("Queue maintenance").

  - importPending/importBlocked/importFailed:
      * exactly one importable file (Radarr reports no rejections), e.g. "matched by ID,
        Manual Import required" -> ManualImport into the queued movie (copy for torrents
        to keep hardlinks, move for usenet)
      * same release as the existing file, or every file rejected as "not an upgrade"
        (e.g. an AI upscale caught by a negative custom format) -> blocklist + remove
  - library: a file shorter than MIN_RUNTIME_RATIO of the movie's runtime is almost
    certainly a different movie with the same title and year (e.g. a mockbuster)
      -> blocklist the grab, delete the file and its torrent, re-search if available
"""
import os, urllib.parse
from datetime import datetime
from arr_maint import Arr, DRY, NOT_UPGRADE, norm, stem

MIN_RUNTIME = float(os.environ.get("MIN_RUNTIME_RATIO", "0.7"))


def minutes(run_time):
    """Radarr's mediaInfo runTime ("1:26:03", "26:03") in minutes, or None."""
    try:
        parts = [float(x) for x in (run_time or "").split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds / 60


def when(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def same_as_existing(cand, mf):
    """True if the downloaded file is the release already in the library."""
    if not mf:
        return False
    names = {norm(mf.get("sceneName")), stem(mf.get("originalFilePath"))} - {""}
    return cand.get("size") == mf.get("size") or stem(cand.get("path")) in names


class App(Arr):
    name = "Radarr"
    url = "http://radarr:7878"
    media_id = "movieId"
    media = "movie"
    queue_params = "includeMovie=true&includeUnknownMovieItems=true"
    category_field = "movieCategory"
    missing_command = {"name": "MoviesSearch"}
    missing_hours = 24.0
    tag = "movie_camera"

    def search_missing(self):
        # API commands are always manual in Radarr, bypassing availability checks.
        queued = {r.get("movieId") for r in self.api(f"/queue?pageSize=2000&{self.queue_params}")["records"]}
        movies = self.api("/movie")
        ids = [m["id"] for m in movies
               if m["monitored"] and not m["hasFile"] and m["isAvailable"] and m["id"] not in queued]
        if not ids:
            return None
        self.api("/command", "POST", {"name": "MoviesSearch", "movieIds": ids})
        return f"MoviesSearch ({len(ids)} available missing movies)"

    def grab_for(self, movie_id, mf):
        """The history 'grabbed' event that produced the movie file, or None."""
        history = self.api(f"/history/movie?movieId={movie_id}")
        added = when(mf["dateAdded"])
        imported = next((h for h in history if h["eventType"] == "downloadFolderImported" and h.get("downloadId")
                         and ((h.get("data") or {}).get("importedPath") == mf.get("path")
                              or abs((when(h["date"]) - added).total_seconds()) < 300)), None)
        if not imported:
            return None
        return next((h for h in history if h["eventType"] == "grabbed"
                     and (h.get("downloadId") or "").lower() == imported["downloadId"].lower()), None)

    def check_library(self):
        actions, needs_user = [], {}
        for m in self.api("/movie"):
            mf = m.get("movieFile") or {}
            got, want = minutes((mf.get("mediaInfo") or {}).get("runTime")), m.get("runtime") or 0
            if not got or not want or got >= MIN_RUNTIME * want:
                continue
            name, short = f"{m['title']} ({m['year']})", f"file runs {got:.0f} of {want} min"
            grab = self.grab_for(m["id"], mf)
            if not grab:
                needs_user[f"short:{mf['id']}"] = (f"{name}: {short}, likely a different movie; no grab to blocklist"
                                                   f" | {mf.get('relativePath', '')[:80]}")
            elif DRY:
                actions.append(f"DRY would reject {name}: {short}")
            else:
                self.api(f"/history/failed/{grab['id']}", "POST", {})
                self.api(f"/moviefile/{mf['id']}", "DELETE")
                if self.qbit:
                    self.qbit.delete(grab["downloadId"])
                # A manual API search would bypass availability, so unreleased movies wait.
                if m["isAvailable"]:
                    self.api("/command", "POST", {"name": "MoviesSearch", "movieIds": [m["id"]]})
                actions.append(f"{name}: {short} -> blocklisted, deleted, "
                               + ("re-searching" if m["isAvailable"] else "search waits for release"))
        return actions, needs_user

    def label(self, rows):
        movie = rows[0].get("movie") or {}
        return f"{movie.get('title', '?')} ({movie.get('year', '')})"

    def fix_import(self, rows, torrent):
        r = rows[0]
        mf = self.api(f"/movie/{r['movieId']}").get("movieFile")
        cands = self.api("/manualimport?" + urllib.parse.urlencode({"downloadId": r["downloadId"], "filterExistingFiles": "true"}))
        if not cands:
            return None, "no importable files found in the download"
        other = {(c.get("movie") or {}).get("id") for c in cands} - {None, r["movieId"]}
        if other:
            return None, f"files match a different movie (id {sorted(other)})"
        if any(same_as_existing(c, mf) for c in cands):
            self.remove(rows)
            return "same release as the existing file -> blocklisted", None
        ok = [c for c in cands if not c.get("rejections")]
        if len(ok) == 1:
            c = ok[0]
            if DRY:
                return f"DRY would import {os.path.basename(c['path'])} ({'copy' if torrent else 'move'})", None
            before = (mf or {}).get("id")
            cid = self.api("/command", "POST", {"name": "ManualImport", "importMode": "copy" if torrent else "move", "files": [{
                "path": c["path"], "movieId": r["movieId"], "quality": c["quality"], "languages": c.get("languages", []),
                "releaseGroup": c.get("releaseGroup"), "indexerFlags": c.get("indexerFlags", 0), "downloadId": r["downloadId"]}]})["id"]
            self.wait(cid)
            after = (self.api(f"/movie/{r['movieId']}").get("movieFile") or {}).get("id")
            if after and after != before:
                return f"imported {os.path.basename(c['path'])}", None
            return None, "manual import ran but the movie file did not change"
        reasons = [x["reason"] for c in cands for x in c.get("rejections", [])]
        if not ok and reasons and all(NOT_UPGRADE.search(x) for x in reasons):
            self.remove(rows)
            return "not an upgrade -> blocklisted", None
        if len(ok) > 1:
            return None, f"{len(ok)} importable files, ambiguous"
        return None, "; ".join(dict.fromkeys(reasons))[:200] or "unknown import problem"
