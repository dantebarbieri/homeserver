import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1] / "dockerfiles" / "arr-maint"
spec = importlib.util.spec_from_file_location("arr_maint", ROOT / "arr_maint.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
with patch.dict(sys.modules, {"arr_maint": engine}):
    spec = importlib.util.spec_from_file_location("lidarr_rules", ROOT / "lidarr.py")
    lidarr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lidarr)


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
        self.app = lidarr.App()
        self.app.wait = Mock()
        self.app.api = Mock(side_effect=self.api)

    def api(self, path, method="GET", body=None):
        if path == "/album/14060":
            album = copy.deepcopy(self.album)
            if self.posts() and self.status == "completed":
                album["statistics"]["trackFileCount"] = 1
            return album
        if path == "/track?albumReleaseId=37608":
            return [self.track]
        if path.startswith("/manualimport?"):
            return [self.item]
        if path == "/command" and method == "POST":
            return {"id": 99}
        if path == "/command/99":
            return {"status": self.status}
        raise AssertionError((path, method, body))

    def posts(self):
        return [c.args for c in self.app.api.call_args_list if c.args[1:2] == ("POST",)]

    def run_import(self, mode="copy", dry=False):
        with patch.object(lidarr, "DRY", dry):
            return self.app.import_dir(str(self.path), 14060, mode, "download")

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
        rows = [{"albumId": 14060, "outputPath": str(self.path), "downloadId": "download"}]
        self.app.remove = Mock()
        with patch.object(lidarr, "DRY", False):
            done, why = self.app.fix_import(rows, torrent=True)
        self.assertTrue(done.startswith("imported 1/1"))
        self.assertIsNone(why)
        self.app.remove.assert_not_called()

    def test_directory_import_retains_existing_behavior(self):
        with patch.object(lidarr, "DRY", False):
            self.assertTrue(self.app.import_dir(self.tmp.name, 14060, "copy").startswith("imported 1/1"))
        self.assertEqual(self.posts()[0][2]["files"][0]["path"], str(self.path))
        self.assertFalse(any(c.args[0] == "/command/99" for c in self.app.api.call_args_list))

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

    def test_failed_or_unfinished_command_is_not_reported_as_imported(self):
        for status in ("failed", "started", "queued", "aborted"):
            with self.subTest(status=status):
                self.app.api.reset_mock()
                self.status = status
                self.assertFalse(self.run_import().startswith("imported"))


if __name__ == "__main__":
    unittest.main()
