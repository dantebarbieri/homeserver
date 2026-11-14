import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).parents[1] / "dockerfiles" / "arr-maint"
spec = importlib.util.spec_from_file_location("arr_maint", ROOT / "arr_maint.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
with patch.dict(sys.modules, {"arr_maint": engine}):
    spec = importlib.util.spec_from_file_location("lidarr_rules", ROOT / "lidarr.py")
    lidarr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lidarr)

DOWNLOAD = "305F366AE3B646D202732EED072406AD26151F99"


class SingleFileImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "01 These Are The Times (feat. JRM).mp3"
        self.path.touch()
        self.album = {
            "id": 14060, "artistId": 678,
            "releases": [{"id": 37608, "trackCount": 1, "monitored": True, "format": "Digital Media"}],
            "statistics": {"trackFileCount": 0, "trackCount": 1},
        }
        self.track = {"id": 255376, "title": "These Are the Times",
                      "mediumNumber": 1, "absoluteTrackNumber": 1}
        self.item = {
            "path": str(self.path), "artist": {"id": 678}, "album": {"id": 14060},
            "albumReleaseId": 37608, "tracks": [self.track], "quality": {"quality": {"id": 4}},
        }
        self.status = "completed"
        self.written = 1  # files left in the library once a ManualImport ran, whatever its status says
        self.more_tracks, self.more_items = [], []
        self.native_passes = []  # per /manualimport call: {file index: album id Lidarr maps it to, None when unidentified}
        self.queue = []
        self.state = {}
        self.app = lidarr.App()
        self.app.wait = Mock()
        self.app.qbit = Mock()
        self.app.api = Mock(side_effect=self.api)
        self.save_state = Mock(side_effect=lambda name, value: self.state.__setitem__(name, copy.deepcopy(value)))
        for name, fake in (("load_state", lambda name, default: copy.deepcopy(self.state.get(name, default))),
                           ("save_state", self.save_state)):
            patcher = patch.object(lidarr, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_second_track(self):
        second = Path(self.tmp.name) / "02 Another Song.mp3"
        second.touch()
        self.more_tracks.append({"id": 255377, "title": "Another Song", "mediumNumber": 1, "absoluteTrackNumber": 2})
        self.more_items.append({"path": str(second), "quality": {"quality": {"id": 4}}})
        self.album["releases"][0]["trackCount"] = 2
        self.album["statistics"]["trackCount"] = 2
        self.written = 2

    def api(self, path, method="GET", body=None):
        if path == "/album/14060":
            album = copy.deepcopy(self.album)
            if self.posts():
                album["statistics"]["trackFileCount"] = self.written
            return album
        if path == "/track?albumReleaseId=37608":
            return [self.track, *self.more_tracks]
        if path.startswith("/manualimport?"):
            items = copy.deepcopy([self.item, *self.more_items])
            for index, album in (self.native_passes.pop(0) if self.native_passes else {}).items():
                items[index].update(artist={"id": 678} if album else None, album={"id": album} if album else None)
            return items
        if path == "/command" and method == "POST":
            return {"id": 99}
        if path == "/command/99":
            return {"status": self.status}
        if path == "/queue/details?albumIds=14060":
            return copy.deepcopy(self.queue)
        if path.startswith("/queue?"):
            return {"records": copy.deepcopy(self.queue), "totalRecords": len(self.queue)}
        if path == "/downloadclient":
            return []
        if path.startswith("/queue/bulk"):
            return None
        raise AssertionError((path, method, body))

    def posts(self):
        return [c.args for c in self.app.api.call_args_list if c.args[1:2] == ("POST",)]

    def stuck(self, protocol="TorrentDownloadProtocol", state="importFailed", download=DOWNLOAD):
        return {"id": 1679392615, "albumId": 14060, "downloadId": download, "protocol": protocol,
                "trackedDownloadState": state, "trackedDownloadStatus": "warning",
                "title": "Martin Garrix - These Are the Times", "outputPath": str(self.path)}

    def run_import(self, mode="copy", dry=False):
        with patch.object(lidarr, "DRY", dry):
            return self.app.import_dir(str(self.path), 14060, mode, "download")

    def fix(self, protocol="TorrentDownloadProtocol", dry=False, path=None):
        row = self.stuck(protocol)
        row["outputPath"] = path or row["outputPath"]
        with patch.object(lidarr, "DRY", dry), patch.object(engine, "DRY", dry):
            return self.app.fix_import([row], torrent=engine.is_torrent(row))

    def test_existing_single_file_is_imported_with_native_track_mapping(self):
        self.assertTrue(self.run_import().startswith("imported 1/1"))
        payload = self.posts()[0][2]
        self.assertEqual(payload["importMode"], "copy")
        self.assertFalse(payload["replaceExistingFiles"])
        self.assertEqual(payload["files"][0]["path"], str(self.path))
        self.assertEqual(payload["files"][0]["trackIds"], [255376])
        self.assertEqual(payload["files"][0]["downloadId"], "download")
        self.assertTrue(payload["files"][0]["disableReleaseSwitching"])
        self.assertFalse(any(c.args[1:2] == ("PUT",) for c in self.app.api.call_args_list))

    def test_usenet_keeps_move_mode(self):
        self.run_import(mode="move")
        self.assertEqual(self.posts()[0][2]["importMode"], "move")

    def test_dry_run_does_not_import(self):
        self.assertTrue(self.run_import(dry=True).startswith("DRY"))
        self.assertEqual(self.posts(), [])
        self.app.wait.assert_not_called()

    def test_missing_or_non_audio_path_is_not_imported(self):
        self.path.unlink()
        self.assertEqual(self.run_import(), "no folder")
        self.path = Path(self.tmp.name) / "cover.jpg"
        self.path.touch()
        self.assertEqual(self.run_import(), "no audio files")
        self.assertEqual(self.posts(), [])

    def test_unmonitored_or_multi_track_release_is_not_selected(self):
        for field, value in (("monitored", False), ("trackCount", 2)):
            with self.subTest(field=field):
                self.album["releases"][0][field] = value
                self.run_import()
                self.assertEqual(self.posts(), [])
                self.album["releases"][0][field] = True if field == "monitored" else 1

    def test_single_file_does_not_override_native_identity_mapping(self):
        for change in (
            {"album": {"id": 999}}, {"artist": {"id": 999}}, {"albumReleaseId": 999},
            {"tracks": [{"id": 999}]}, {"tracks": []}, {"tracks": None},
            {"album": None}, {"artist": None},
            {"path": "another-file.mp3"},
        ):
            with self.subTest(change=change):
                original = self.item.copy()
                self.item.update(change)
                self.run_import()
                self.assertEqual(self.posts(), [])
                self.item = original

    def test_single_file_does_not_replace_existing_album_files(self):
        self.album["statistics"]["trackFileCount"] = 1
        self.run_import()
        self.assertEqual(self.posts(), [])

    def test_incomplete_release_track_metadata_is_not_imported(self):
        original = self.api
        self.app.api.side_effect = lambda path, *args: (
            [] if path.startswith("/track?") else original(path, *args)
        )
        self.run_import()
        self.assertEqual(self.posts(), [])

    def test_fix_import_accepts_single_file_without_removing_download(self):
        self.app.remove = Mock()
        done, why = self.fix()
        self.assertTrue(done.startswith("imported 1/1"))
        self.assertIsNone(why)
        self.app.remove.assert_not_called()

    def test_directory_import_retains_existing_behavior(self):
        self.assertTrue(self.run_dir().startswith("imported 1/1"))
        self.assertEqual(self.posts()[0][2]["files"][0]["path"], str(self.path))

    def directory_mapping(self, filenames, titles, artist="Luis Fonsi"):
        self.path.unlink()
        self.album["artist"] = {"artistName": artist}
        self.album["releases"][0]["trackCount"] = len(titles)
        self.album["statistics"]["trackCount"] = len(titles)
        self.written = len(titles)
        tracks = [{"id": 255376 + i, "title": title, "mediumNumber": 1, "absoluteTrackNumber": i + 1}
                  for i, title in enumerate(titles)]
        items = []
        for filename in filenames:
            path = Path(self.tmp.name) / filename
            path.touch()
            items.append({"path": str(path), "artist": {"id": 678}, "album": {"id": 14060},
                          "quality": {"quality": {"id": 4}}})
        self.track, self.more_tracks = tracks[0], tracks[1:]
        self.item, self.more_items = items[0], items[1:]

    def test_alphabetical_artist_prefixed_files_map_by_exact_title_not_position(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Despacito (Remix).flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Despacito (remix)", "Apaga la luz"],
        )
        self.assertTrue(self.run_dir().startswith("imported 3/3"))
        files = self.posts()[0][2]["files"]
        self.assertEqual([f["trackIds"] for f in files], [[255378], [255377], [255376]])

    def test_reordered_edition_maps_titles_with_feature_credits(self):
        self.directory_mapping(
            ["01. Satellites.mp3", "02. Higher (feat. Betty Who).mp3",
             "03. Echoes.mp3", "04. Give Me Love [feat. Calum Scott].mp3"],
            ["Give Me Love", "Higher", "Satellites", "Echoes"], artist="Don Diablo",
        )
        self.assertTrue(self.run_dir().startswith("imported 4/4"))
        self.assertEqual([f["trackIds"] for f in self.posts()[0][2]["files"]],
                         [[255378], [255377], [255379], [255376]])

    def test_exact_title_fallback_requires_native_artist_and_album_agreement(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        for field in ("artist", "album"):
            with self.subTest(field=field):
                original = self.item[field]
                self.item[field] = {"id": 999}
                self.assertEqual(self.run_dir(), "title mapping does not match native artist/album")
                self.assertEqual(self.posts(), [])
                self.item[field] = original

    def test_exact_title_fallback_confirms_files_across_unstable_native_passes(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.native_passes = [{0: None}, {1: None}]
        self.assertTrue(self.run_dir().startswith("imported 2/2"))
        self.assertEqual(len(self.posts()), 1)

    def test_exact_title_fallback_rejects_files_native_never_identifies(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.native_passes = [{0: None}] * 3
        self.assertEqual(self.run_dir(), "title mapping does not match native artist/album")
        self.assertEqual(self.posts(), [])

    def test_exact_title_fallback_rejects_when_a_later_native_pass_disagrees(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.native_passes = [{0: None}, {1: 999}]
        self.assertEqual(self.run_dir(), "title mapping does not match native artist/album")
        self.assertEqual(self.posts(), [])

    def test_exact_title_fallback_keeps_version_qualifiers(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz (Live).flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.assertTrue(self.run_dir().startswith("low title match"))
        self.assertEqual(self.posts(), [])

    def test_exact_title_fallback_requires_a_bijection(self):
        self.directory_mapping(
            ["01. Luis Fonsi - Sola.flac", "02. Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.assertTrue(self.run_dir().startswith("low title match"))
        self.assertEqual(self.posts(), [])

    def test_exact_title_fallback_rejects_duplicate_target_titles_and_missing_metadata(self):
        files = ["Luis Fonsi - Sola.flac", "Luis Fonsi - Apaga La Luz.flac"]
        tracks = [{"id": 1, "title": "Sola"}, {"id": 2, "title": "Sola"}]
        self.assertIsNone(lidarr.title_mapping(files, tracks, "Luis Fonsi"))
        self.assertIsNone(lidarr.title_mapping(files, tracks[:1], "Luis Fonsi"))

    def test_exact_title_fallback_keeps_original_and_remix_distinct(self):
        files = ["Luis Fonsi - Despacito (Remix).flac", "Luis Fonsi - Despacito.flac"]
        tracks = [{"id": 1, "title": "Despacito"}, {"id": 2, "title": "Despacito (remix)"}]
        self.assertEqual([t["id"] for t in lidarr.title_mapping(files, tracks, "Luis Fonsi")], [2, 1])

    def test_exact_title_fallback_dry_run_does_not_change_edition_or_import(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.album["releases"][0]["monitored"] = False
        with patch.object(lidarr, "DRY", True):
            self.assertTrue(self.app.import_dir(self.tmp.name, 14060, "copy").startswith("DRY"))
        self.assertEqual(self.posts(), [])
        self.assertFalse(any(c.args[1:2] == ("PUT",) for c in self.app.api.call_args_list))

    def test_exact_title_fallback_does_not_switch_an_edition_with_existing_files(self):
        self.directory_mapping(
            ["Luis Fonsi - Apaga La Luz.flac", "Luis Fonsi - Sola.flac"],
            ["Sola", "Apaga la luz"],
        )
        self.album["releases"][0]["monitored"] = False
        self.album["statistics"]["trackFileCount"] = 1
        self.assertIn("not switching", self.run_dir())
        self.assertEqual(self.posts(), [])
        self.assertFalse(any(c.args[1:2] == ("PUT",) for c in self.app.api.call_args_list))

    def test_low_title_match_does_not_import(self):
        self.track["title"] = "Unrelated Song"
        self.assertTrue(self.run_import().startswith("low title match"))
        self.assertEqual(self.posts(), [])

    def test_different_version_is_not_imported_as_original(self):
        for version in ("BEAUZ Remix", "Radio Edit", "Live", "Acoustic", "Instrumental", "Karaoke", "Mix", "Version"):
            with self.subTest(version=version):
                self.path = Path(self.tmp.name) / f"These Are the Times ({version}).mp3"
                self.path.touch()
                self.item["path"] = str(self.path)
                self.run_import()
                self.assertEqual(self.posts(), [])

    def run_dir(self):
        with patch.object(lidarr, "DRY", False):
            return self.app.import_dir(self.tmp.name, 14060, "copy", "download")

    def forget(self, row, dry=False):
        with patch.object(lidarr, "DRY", dry), patch.object(engine, "DRY", dry):
            self.app.forget([row])

    def test_failed_or_unfinished_command_is_not_reported_as_imported(self):
        self.written = 0
        for status in ("failed", "started", "queued", "aborted"):
            with self.subTest(status=status):
                self.app.api.reset_mock()
                self.status = status
                self.assertEqual(self.run_import(), f"import command 99 {status}; 0/1 files, import not confirmed")

    def test_completed_command_without_files_is_not_reported_as_imported(self):
        self.written = 0
        self.assertEqual(self.run_import(), "import command 99 completed; 0/1 files, import not confirmed")

    def test_completed_directory_import_must_cover_every_file(self):
        self.add_second_track()
        self.written = 1
        self.assertEqual(self.run_dir(), "import command 99 completed; 1/2 files, import not confirmed")
        self.app.api.reset_mock()
        self.written = 2
        self.assertTrue(self.run_dir().startswith("imported 2/2"))

    def test_failed_command_is_confirmed_by_the_files_it_left(self):
        # Lidarr can throw after importing; what counts is that the album now has its files.
        self.status = "failed"
        for run in (self.run_import, self.run_dir):
            with self.subTest(run=run.__name__):
                self.app.api.reset_mock()
                res = run()
                self.assertTrue(res.startswith("imported 1/1"), res)
                self.assertTrue(res.endswith("; command 99 failed after importing"), res)

    def test_unfinished_command_is_not_confirmed_even_when_files_appeared(self):
        for status in ("started", "queued", "aborted"):
            with self.subTest(status=status):
                self.app.api.reset_mock()
                self.status = status
                self.assertEqual(self.run_import(), f"import command 99 {status}; 1/1 files, import not confirmed")

    def test_failed_directory_import_must_cover_every_file(self):
        self.status = "failed"
        self.add_second_track()
        self.assertTrue(self.run_dir().startswith("imported 2/2"))
        self.app.api.reset_mock()
        self.written = 1
        self.assertEqual(self.run_dir(), "import command 99 failed; 1/2 files, import not confirmed")

    def test_failed_directory_import_on_an_album_with_files_is_not_confirmed(self):
        self.status = "failed"
        self.album["statistics"]["trackFileCount"] = 1
        self.assertEqual(self.run_dir(), "import command 99 failed; 1/1 files, import not confirmed")

    def test_fix_import_clears_the_entry_lidarr_leaves_stuck_after_a_failed_command(self):
        self.status = "failed"
        self.queue = [self.stuck()]
        self.app.forget = Mock()
        done, why = self.fix()
        self.assertIsNone(why)
        self.assertIn("failed after importing", done)
        self.assertTrue(done.endswith("; queue entry cleared"), done)
        self.app.forget.assert_called_once_with(self.queue)
        self.assertEqual(len(self.posts()), 1)
        # Remembered before its entry is cleared, forgotten once that worked.
        self.assertEqual([DOWNLOAD in c.args[1] for c in self.save_state.call_args_list], [True, False])

    def test_fix_import_leaves_an_entry_lidarr_finished_alone(self):
        self.queue = [self.stuck(state="imported")]
        self.app.forget = Mock()
        done, why = self.fix()
        self.assertTrue(done.startswith("imported 1/1"), done)
        self.assertNotIn("queue entry cleared", done)
        self.assertIsNone(why)
        self.app.forget.assert_not_called()
        self.assertEqual(self.state["imported.json"], {})

    def test_settle_only_forgets_the_stuck_entries_of_this_download(self):
        self.queue = [self.stuck(download="OTHER"), self.stuck(state="downloading"), self.stuck()]
        self.app.forget = Mock()
        self.assertEqual(self.app.settle([self.stuck()]), 1)
        self.app.forget.assert_called_once_with([self.stuck()])

    def test_failure_to_clear_the_entry_is_retried_without_importing_again(self):
        self.queue = [self.stuck()]
        self.app.forget = Mock(side_effect=RuntimeError("boom"))
        done, why = self.fix()
        self.assertIsNone(done)
        self.assertIn("imported 1/1", why)
        self.assertIn("clearing its queue entry failed (RuntimeError: boom)", why)
        self.assertIn(DOWNLOAD, self.state["imported.json"])
        self.app.forget = Mock()
        done, why = self.fix()
        self.assertIsNone(why)
        self.assertEqual(done, "already imported; queue entry cleared")
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.state["imported.json"], {})

    def test_unconfirmed_import_is_not_remembered(self):
        self.status, self.written = "started", 0
        done, why = self.fix()
        self.assertIsNone(done)
        self.assertIn("import not confirmed", why)
        self.save_state.assert_not_called()

    def test_partial_import_is_neither_remembered_nor_cleared(self):
        self.add_second_track()
        self.written = 1
        self.queue = [self.stuck()]
        self.app.forget = Mock()
        done, why = self.fix(path=self.tmp.name)
        self.assertIsNone(done)
        self.assertEqual(why, "import command 99 completed; 1/2 files, import not confirmed")
        self.save_state.assert_not_called()
        self.app.forget.assert_not_called()

    def test_dry_run_neither_imports_nor_clears_anything(self):
        self.queue = [self.stuck()]
        self.app.forget = Mock()
        done, why = self.fix(dry=True)
        self.assertTrue(done.startswith("DRY would import"), done)
        self.assertIsNone(why)
        self.assertEqual(self.posts(), [])
        self.app.forget.assert_not_called()
        self.save_state.assert_not_called()
        self.assertFalse(any(c.args[0].startswith("/queue/details") for c in self.app.api.call_args_list))

    def test_dry_run_reports_clearing_the_entry_of_an_earlier_import(self):
        self.state["imported.json"] = {DOWNLOAD: time.time()}
        self.queue = [self.stuck()]
        self.app.forget = Mock()
        done, why = self.fix(dry=True)
        self.assertEqual(done, "DRY would clear the queue entry of an earlier import")
        self.assertIsNone(why)
        self.assertEqual(self.posts(), [])
        self.app.forget.assert_not_called()
        self.save_state.assert_not_called()

    def test_remembered_imports_expire(self):
        now = time.time()
        self.state["imported.json"] = {"OLD": now - lidarr.IMPORTED_TTL - 1, "NEW": now}
        self.assertEqual(set(self.app.marks()), {"NEW"})

    def test_run_copies_a_torrent_and_clears_the_entry_lidarr_leaves_stuck(self):
        self.status = "failed"
        self.queue = [self.stuck()]
        self.app.missing_hours = self.app.upgrade_hours = 0
        self.app.summary = Mock(return_value=None)
        self.app.connect_qbit = Mock(return_value=self.app.qbit)
        with patch.object(engine, "DRY", False), patch.object(lidarr, "DRY", False), \
                patch.object(engine, "QBIT_USER", "user"), patch.object(engine, "ntfy"), \
                patch.object(engine, "save_state"), patch.object(engine, "log") as log, \
                patch.object(engine, "load_state",
                             side_effect=lambda name, default: {DOWNLOAD: 0} if name == "seen.json" else default):
            self.app.run()
        logged = [" ".join(str(a) for a in c.args) for c in log.call_args_list]
        self.assertEqual(self.posts()[0][2]["importMode"], "copy")
        self.assertTrue(any(l.startswith("ACTION:") and l.endswith("; queue entry cleared") for l in logged), logged)
        self.assertFalse(any(l.startswith("NEEDS USER:") for l in logged), logged)
        self.assertIn(call("torrents/setCategory", {"hashes": DOWNLOAD.lower(), "category": lidarr.QBIT_MANUAL_CATEGORY}),
                      self.app.qbit.post.call_args_list)
        self.assertFalse(any(c.args[1:2] == ("DELETE",) for c in self.app.api.call_args_list))

    def test_forget_moves_a_torrent_to_the_manual_category_so_it_keeps_seeding(self):
        self.forget(self.stuck())
        self.assertEqual(self.app.qbit.post.call_args_list, [
            call("torrents/createCategory", {"category": lidarr.QBIT_MANUAL_CATEGORY, "savePath": lidarr.QBIT_MANUAL_PATH}),
            call("torrents/setCategory", {"hashes": DOWNLOAD.lower(), "category": lidarr.QBIT_MANUAL_CATEGORY}),
            call("torrents/setLocation", {"hashes": DOWNLOAD.lower(), "location": lidarr.QBIT_MANUAL_PATH}),
        ])
        self.app.api.assert_not_called()

    def test_forget_tolerates_an_existing_category_but_no_other_error(self):
        for code, calls in ((409, 3), (500, 1)):
            with self.subTest(code=code):
                def post(path, data, code=code):
                    if path == "torrents/createCategory":
                        raise urllib.error.HTTPError("http://qbit", code, "error", {}, None)
                self.app.qbit.post = Mock(side_effect=post)
                if code == 409:
                    self.forget(self.stuck())
                else:
                    with self.assertRaises(urllib.error.HTTPError):
                        self.forget(self.stuck())
                self.assertEqual(self.app.qbit.post.call_count, calls)

    def test_forget_only_drops_usenet_and_clientless_entries_from_the_queue(self):
        qbit = self.app.qbit
        for client, protocol in ((qbit, "UsenetDownloadProtocol"), (None, "TorrentDownloadProtocol")):
            with self.subTest(protocol=protocol, client=client is not None):
                self.app.api.reset_mock()
                self.app.qbit = client
                self.forget(self.stuck(protocol))
                self.app.api.assert_called_once_with("/queue/bulk?removeFromClient=false&blocklist=false", "DELETE",
                                                     {"ids": [1679392615]})
        qbit.post.assert_not_called()

    def test_forget_changes_nothing_in_a_dry_run(self):
        for protocol in ("TorrentDownloadProtocol", "UsenetDownloadProtocol"):
            with self.subTest(protocol=protocol):
                self.forget(self.stuck(protocol), dry=True)
        self.app.qbit.post.assert_not_called()
        self.app.api.assert_not_called()


class ProtocolTests(unittest.TestCase):
    def test_torrent_protocols_of_every_app_are_recognized(self):
        for protocol, expected in (("torrent", True), ("TorrentDownloadProtocol", True), ("usenet", False),
                                   ("UsenetDownloadProtocol", False), ("unknown", False), ("", False), (None, False)):
            with self.subTest(protocol=protocol):
                self.assertIs(engine.is_torrent({"protocol": protocol}), expected)
        self.assertIs(engine.is_torrent({}), False)


class QueueRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = lidarr.App()
        self.app.missing_hours = self.app.upgrade_hours = 0
        self.app.summary = Mock(return_value=None)
        self.app.fix_import = Mock(return_value=("imported", None))
        self.app.forget = Mock()

    def row(self, protocol="TorrentDownloadProtocol", state="importFailed", status="warning", album=14060, path=""):
        return {"id": 1, "downloadId": DOWNLOAD, "protocol": protocol, "trackedDownloadState": state,
                "trackedDownloadStatus": status, "albumId": album, "title": "Martin Garrix - These Are the Times",
                "outputPath": path, "statusMessages": [], "artist": {"artistName": "Martin Garrix"},
                "album": {"title": "These Are the Times"}}

    def run_queue(self, *rows):
        self.app.api = Mock(side_effect=lambda path, *a: {"records": list(rows), "totalRecords": len(rows)}
                            if path.startswith("/queue?") else [])
        with patch.object(engine, "DRY", False), patch.object(lidarr, "DRY", False), \
                patch.object(engine, "QBIT_USER", ""), patch.object(engine, "ntfy"), patch.object(engine, "save_state"), \
                patch.object(engine, "log") as log, \
                patch.object(engine, "load_state",
                             side_effect=lambda name, default: {DOWNLOAD: 0} if name == "seen.json" else default):
            self.app.run()
        return [" ".join(str(a) for a in c.args) for c in log.call_args_list]

    def test_lidarr_torrents_are_flagged_as_torrents(self):
        for protocol, expected in (("TorrentDownloadProtocol", True), ("UsenetDownloadProtocol", False)):
            with self.subTest(protocol=protocol):
                self.app.fix_import.reset_mock()
                self.run_queue(self.row(protocol))
                self.app.fix_import.assert_called_once()
                self.assertIs(self.app.fix_import.call_args.args[1], expected)

    def test_unmatched_torrent_hardlinked_into_the_library_is_forgotten(self):
        library = Path(self.tmp.name) / "library.mp3"
        library.touch()
        download = Path(self.tmp.name) / "download.mp3"
        try:
            os.link(library, download)
        except OSError:
            self.skipTest("hardlinks are not supported here")
        logged = self.run_queue(self.row(album=None, path=str(download)))
        self.app.forget.assert_called_once()
        self.assertTrue(any("1/1 files already in library -> forgotten" in l for l in logged), logged)

    def test_unmatched_torrent_that_is_not_in_the_library_needs_the_user(self):
        download = Path(self.tmp.name) / "download.mp3"
        download.touch()
        logged = self.run_queue(self.row(album=None, path=str(download)))
        self.app.forget.assert_not_called()
        self.assertTrue(any(l.startswith("NEEDS USER:") and "no artist/album match" in l for l in logged), logged)

    def test_torrent_warnings_are_left_to_the_dead_torrent_rule_but_usenet_ones_are_not(self):
        for protocol, alerted in (("TorrentDownloadProtocol", False), ("UsenetDownloadProtocol", True)):
            with self.subTest(protocol=protocol):
                logged = self.run_queue(self.row(protocol, state="downloading", status="warning"))
                self.assertEqual(any(l.startswith("NEEDS USER:") for l in logged), alerted, logged)


if __name__ == "__main__":
    unittest.main()
