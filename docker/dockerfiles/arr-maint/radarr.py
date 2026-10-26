"""Radarr rules. See docker/docs/RADARR.md ("Queue maintenance").

  - importPending/importBlocked/importFailed:
      * exactly one importable file (Radarr reports no rejections), e.g. "matched by ID,
        Manual Import required" -> ManualImport into the queued movie (copy for torrents
        to keep hardlinks, move for usenet)
      * same release as the existing file, or every file rejected as "not an upgrade"
        (e.g. an AI upscale caught by a negative custom format) -> blocklist + remove
"""
import os, urllib.parse
from arr_maint import Arr, DRY, NOT_UPGRADE, norm, stem


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
    missing_command = {"name": "MissingMoviesSearch", "filterKey": "monitored", "filterValue": "true"}
    missing_hours = 24.0
    tag = "movie_camera"

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
