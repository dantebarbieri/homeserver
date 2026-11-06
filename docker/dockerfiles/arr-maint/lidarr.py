"""Lidarr rules. See docker/docs/MUSIC.md ("Queue maintenance").

  - importFailed/Pending/Blocked: if the file count matches another edition of the album and
    the titles match, ManualImport into it (copy for torrents so they keep seeding, move for
    usenet); never switches editions on an album that already has files, since that unlinks them
  - a completed single audio file (outputPath is a file, not a folder) is imported only into an
    empty, monitored one-track release when Lidarr's own manual-import mapping (artist, album,
    release, track) agrees and no remix/live/edit qualifier differs; anything else is left for the user
  - an import counts as done when the album has its files, even if Lidarr fails the command
    afterwards; the queue entry it then leaves stuck is cleared (see settle), and the download is
    remembered in imported.json until that worked, so it is never imported twice
  - a single/EP grabbed for an album (<=4 files for an 8+ track album) -> blocklist + re-search
  - "forget" moves torrents to QBIT_MANUAL_CATEGORY instead of using Lidarr's queue Remove,
    which throws a NullReferenceException (HTTP 500) for items without an artist
  - CutoffUnmetAlbumSearch daily, so albums below the Lossless cutoff (MP3 etc.) get upgraded
"""
import os, re, time, difflib, urllib.parse, urllib.error
from arr_maint import Arr, DRY, IMPORT_STATES, is_torrent, load_state, norm, save_state

AUD = (".flac", ".m4a", ".mp3", ".ape", ".wv")
QBIT_MANUAL_CATEGORY = os.environ.get("QBIT_MANUAL_CATEGORY", "music-manual")
QBIT_MANUAL_PATH = os.environ.get("QBIT_MANUAL_PATH", "/data/torrents/music-manual")
IMPORTED_STATE = "imported.json"
IMPORTED_TTL = 14 * 86400


def strip(fname):
    return re.sub(r"^[\d\s.\-_]+", "", os.path.splitext(fname)[0])


def audio_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs if f.lower().endswith(AUD))


class App(Arr):
    name = "Lidarr"
    url = "http://lidarr:8686"
    api_version = "v1"
    media_id = "albumId"
    media = "artist/album"
    queue_params = "includeArtist=true&includeAlbum=true&includeUnknownArtistItems=true"
    category_field = "musicCategory"
    missing_command = {"name": "MissingAlbumSearch"}
    missing_hours = 6.0
    # RSS alone rarely sees lossless releases of older albums, so actively search MP3/lossy albums.
    upgrade_command = {"name": "CutoffUnmetAlbumSearch"}
    upgrade_hours = 24.0
    tag = "musical_note"

    def label(self, rows):
        r = rows[0]
        return f"{(r.get('artist') or {}).get('artistName')} - {(r.get('album') or {}).get('title', '')[:50]}"

    def remove(self, rows):
        # Search explicitly rather than relying on Lidarr's "Redownload Failed" setting.
        if DRY:
            return
        self.api("/queue/bulk?removeFromClient=true&blocklist=true&skipRedownload=true", "DELETE", {"ids": [r["id"] for r in rows]})
        ids = sorted({r["albumId"] for r in rows if r.get("albumId")})
        if ids:
            self.api("/command", "POST", {"name": "AlbumSearch", "albumIds": ids})

    def forget(self, rows):
        if not (self.qbit and is_torrent(rows[0])):
            return super().forget(rows)
        if DRY:
            return
        # Same filesystem, so setLocation is a rename and keeps hardlinks.
        try:
            self.qbit.post("torrents/createCategory", {"category": QBIT_MANUAL_CATEGORY, "savePath": QBIT_MANUAL_PATH})
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
        h = rows[0]["downloadId"].lower()
        self.qbit.post("torrents/setCategory", {"hashes": h, "category": QBIT_MANUAL_CATEGORY})
        self.qbit.post("torrents/setLocation", {"hashes": h, "location": QBIT_MANUAL_PATH})

    def fix_import(self, rows, torrent):
        albums = sorted({r["albumId"] for r in rows})
        if len(albums) > 1:
            return None, f"download covers {len(albums)} albums"
        r = rows[0]
        marks = self.marks()
        if r["downloadId"] in marks:
            # Imported on an earlier run; only clearing its queue entry failed.
            return ("DRY would clear the queue entry of an earlier import", None) if DRY else self.finish(rows, "already imported", marks)
        nfiles = len(audio_files(r.get("outputPath")))
        counts = {x["trackCount"] for x in self.api(f"/album/{r['albumId']}")["releases"]}
        if nfiles and nfiles <= 4 and counts and min(counts) >= 8:
            self.remove(rows)
            return f"wrong release ({nfiles} files) -> blocklisted+re-search", None
        res = self.import_dir(r.get("outputPath") or "", r["albumId"], "copy" if torrent else "move", r["downloadId"])
        if res.startswith("DRY"):
            return res, None
        if not res.startswith("imported"):
            return None, res
        marks[r["downloadId"]] = time.time()
        save_state(IMPORTED_STATE, marks)
        return self.finish(rows, res, marks)

    def marks(self):
        """Downloads imported by this helper whose queue entry has not been cleared yet."""
        now = time.time()
        return {k: v for k, v in load_state(IMPORTED_STATE, {}).items() if now - v < IMPORTED_TTL}

    def finish(self, rows, res, marks):
        try:
            cleared = self.settle(rows)
        except Exception as e:
            return None, f"{res}; clearing its queue entry failed ({type(e).__name__}: {e})"[:300]
        save_state(IMPORTED_STATE, {k: v for k, v in marks.items() if k != rows[0]["downloadId"]})
        return (f"{res}; queue entry cleared" if cleared else res), None

    def settle(self, rows):
        """Forgets the queue entries Lidarr still lists as stuck after an import; returns how many.

        Lidarr v3 can throw a NullReferenceException at the end of a manual import: it reads the
        tracked download's ImportItem, which is unset for a download rebuilt from its history. The
        files are imported by then, but the bookkeeping that marks the download imported is
        skipped, so the entry would stay in importFailed and, as torrents are copied, be imported
        again every run."""
        r = rows[0]
        left = [x for x in self.api(f"/queue/details?albumIds={r['albumId']}")
                if x.get("downloadId") == r["downloadId"] and x.get("trackedDownloadState") in IMPORT_STATES]
        if left:
            self.forget(left)
        return len(left)

    def import_dir(self, folder, album_id, mode, download_id=None, min_score=0.45):
        single_file = os.path.isfile(folder)
        if not (single_file or os.path.isdir(folder)):
            return "no folder"
        files = ([folder] if folder.lower().endswith(AUD) else []) if single_file else audio_files(folder)
        if not files:
            return "no audio files"
        alb = self.api(f"/album/{album_id}")
        before = (alb.get("statistics") or {}).get("trackFileCount", 0)
        best = None
        for rel in [r for r in alb["releases"] if r["trackCount"] == len(files) and
                    (not single_file or r["monitored"])]:
            tr = sorted(self.api(f"/track?albumReleaseId={rel['id']}"), key=lambda t: (t["mediumNumber"], t["absoluteTrackNumber"]))
            if single_file and len(tr) != 1:
                continue
            sc = sum(difflib.SequenceMatcher(None, norm(t["title"]), norm(strip(os.path.basename(f)))).ratio() for f, t in zip(files, tr)) / len(files)
            if not best or sc > best[0]:
                best = (sc, rel, tr)
        if not best:
            return f"{len(files)} files, no release with that count ({sorted({r['trackCount'] for r in alb['releases']})})"
        sc, rel, tr = best
        if sc < min_score:
            return f"low title match {sc:.2f}"
        q = None
        if single_file:
            # A bare file must agree with Lidarr's mapping, not guess an edition or remix.
            if (alb.get("statistics") or {}).get("trackFileCount"):
                return "single-file album already has files; not replacing"
            versions = lambda s: set(re.findall(r"\b(?:remix|mix|live|acoustic|instrumental|karaoke|edit|version)\b", s, re.I))
            if versions(os.path.basename(folder).lower()) != versions(tr[0]["title"].lower()):
                return "single-file version differs from target track"
            q = {i["path"]: i for i in self.api("/manualimport?" + urllib.parse.urlencode({"folder": folder, "filterExistingFiles": "false"}))}
            item = q.get(folder) or {}
            if ((item.get("artist") or {}).get("id") != alb["artistId"] or
                    (item.get("album") or {}).get("id") != album_id or
                    item.get("albumReleaseId") != rel["id"] or
                    [t["id"] for t in (item.get("tracks") or [])] != [t["id"] for t in tr]):
                return "single-file mapping does not match monitored release"
        if DRY:
            return f"DRY would import {len(files)} into {rel['format']} score {sc:.2f}"
        if not rel["monitored"]:
            # Switching the monitored edition unlinks files already imported on another edition.
            if (alb.get("statistics") or {}).get("trackFileCount"):
                return f"album already has {alb['statistics']['trackFileCount']} files on another release; not switching"
            for r in alb["releases"]:
                r["monitored"] = r["id"] == rel["id"]
            self.api(f"/album/{album_id}", "PUT", alb)
        if q is None:
            q = {i["path"]: i for i in self.api("/manualimport?" + urllib.parse.urlencode({"folder": folder, "filterExistingFiles": "false"}))}
        payload = [dict({"path": f, "artistId": alb["artistId"], "albumId": album_id, "albumReleaseId": rel["id"], "trackIds": [t["id"]],
                         "quality": q[f]["quality"], "disableReleaseSwitching": True, "indexerFlags": 0},
                        **({"downloadId": download_id} if download_id else {})) for f, t in zip(files, tr)]
        cid = self.api("/command", "POST", {"name": "ManualImport", "files": payload, "importMode": mode, "replaceExistingFiles": False})["id"]
        self.wait(cid, 60)
        status = self.api(f"/command/{cid}")["status"]
        s = self.api(f"/album/{album_id}")["statistics"]
        have = s["trackFileCount"]
        got = f"{have}/{s['trackCount']}"
        if status == "completed" and have >= len(files):
            return f"imported {got} (score {sc:.2f})"
        if status == "failed" and not before and have >= len(files):
            # Lidarr can throw after importing (see settle), so judge by the files, not the status.
            return f"imported {got} (score {sc:.2f}); command {cid} failed after importing"
        return f"import command {cid} {status}; {got} files, import not confirmed"

    def summary(self):
        albums = self.api("/album")
        st = lambda a: a.get("statistics") or {}
        mon = [a for a in albums if a["monitored"]]
        complete = sum(1 for a in mon if st(a).get("trackCount") and st(a).get("trackFileCount", 0) >= st(a)["trackCount"])
        return f"library: complete {complete}/{len(mon)} | tracks {sum(st(a).get('trackFileCount', 0) for a in albums)}"
