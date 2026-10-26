"""Sonarr rules. See docker/docs/SONARR.md ("Queue maintenance").

Sonarr lists one queue row per episode; the engine groups them by download.
  - importPending/importBlocked/importFailed:
      * one file whose only rejections are episode-numbering parse failures (anime absolute
        numbers read as SxxEyy, "Invalid season or episode", "not found in the grabbed
        release") and a download grabbed for exactly one episode -> ManualImport into that
        episode (copy for torrents to keep hardlinks, move for usenet)
      * same release as the existing file, or every file rejected as "not an upgrade"
        -> blocklist + remove (Sonarr re-searches)
      * quality, language or custom-format rejections are never overridden
"""
import os, re, urllib.parse, urllib.error
from arr_maint import Arr, DRY, NOT_UPGRADE, norm, stem

# Rejections that only mean Sonarr couldn't map the file name to the grabbed episode.
NUMBERING = re.compile(r"not found in the grabbed release|invalid season or episode|unable to (parse|identify)"
                       r"|episode.*(was not|wasn't|not) (found|parsed)|manual import required", re.I)


class App(Arr):
    name = "Sonarr"
    url = "http://sonarr:8989"
    media_id = "seriesId"
    media = "series"
    queue_params = "includeSeries=true&includeEpisode=true&includeUnknownSeriesItems=true"
    category_field = "tvCategory"
    missing_command = {"name": "MissingEpisodeSearch", "monitored": True}
    missing_hours = 168.0
    tag = "tv"

    def label(self, rows):
        r = rows[0]
        eps = sorted((e.get("seasonNumber", 0), e.get("episodeNumber", 0)) for e in (x.get("episode") for x in rows) if e)
        tag = (f" S{eps[0][0]:02d}E{eps[0][1]:02d}" + (f" (+{len(eps) - 1})" if len(eps) > 1 else "")) if eps else ""
        return f"{(r.get('series') or {}).get('title', '?')}{tag}"

    def episode_file(self, eid):
        return self.api(f"/episode/{eid}").get("episodeFileId") or 0

    def same_as_existing(self, cand, eids):
        """True if the downloaded file is the release already in the library for those episodes."""
        for eid in eids:
            fid = self.episode_file(eid)
            if fid:
                ef = self.api(f"/episodefile/{fid}")
                if cand.get("size") == ef.get("size") or stem(cand.get("path")) in {norm(ef.get("sceneName"))} - {""}:
                    return True
        return False

    def fix_import(self, rows, torrent):
        r = rows[0]
        eids = sorted({x["episodeId"] for x in rows if x.get("episodeId")})
        try:
            cands = self.api("/manualimport?" + urllib.parse.urlencode({"downloadId": r["downloadId"], "filterExistingFiles": "true"}))
        except urllib.error.HTTPError as e:
            return None, f"Sonarr could not list the download's files (HTTP {e.code})"
        cands = [c for c in cands or [] if not any(re.search(r"sample", x["reason"], re.I) for x in c.get("rejections", []))]
        if not cands:
            return None, "no importable files found in the download"
        other = {(c.get("series") or {}).get("id") for c in cands} - {None, r["seriesId"]}
        if other:
            return None, f"files match a different series (id {sorted(other)})"
        if len(cands) == 1 and self.same_as_existing(cands[0], eids):
            self.remove(rows)
            return "same release as the existing file -> blocklisted", None
        reasons = [x["reason"] for c in cands for x in c.get("rejections", [])]
        if reasons and all(NOT_UPGRADE.search(x) for x in reasons) and all(c.get("rejections") for c in cands):
            self.remove(rows)
            return "not an upgrade -> blocklisted", None
        c = cands[0]
        rej = [x["reason"] for x in c.get("rejections", [])]
        if len(cands) == 1 and len(eids) == 1 and rej and all(NUMBERING.search(x) for x in rej):
            if DRY:
                return f"DRY would import {os.path.basename(c['path'])} as episode {eids[0]} ({'copy' if torrent else 'move'})", None
            before = self.episode_file(eids[0])
            # Sonarr couldn't parse the episode from the name, so quality and languages come from the grab.
            cid = self.api("/command", "POST", {"name": "ManualImport", "importMode": "copy" if torrent else "move", "files": [{
                "path": c["path"], "folderName": c.get("folderName", ""), "seriesId": r["seriesId"], "episodeIds": eids,
                "quality": r.get("quality") or c.get("quality"), "languages": r.get("languages") or c.get("languages", []),
                "releaseGroup": c.get("releaseGroup"), "indexerFlags": c.get("indexerFlags", 0),
                "releaseType": "singleEpisode", "downloadId": r["downloadId"]}]})["id"]
            self.wait(cid)
            after = self.episode_file(eids[0])
            if after and after != before:
                return f"imported {os.path.basename(c['path'])} (episode numbering mismatch)", None
            return None, "manual import ran but the episode file did not change"
        return None, "; ".join(dict.fromkeys(reasons))[:200] or "stuck with no rejections"
