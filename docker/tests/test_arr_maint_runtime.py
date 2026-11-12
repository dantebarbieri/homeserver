import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1] / "dockerfiles" / "arr-maint"
spec = importlib.util.spec_from_file_location("arr_maint", ROOT / "arr_maint.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
with patch.dict(sys.modules, {"arr_maint": engine}):
    spec = importlib.util.spec_from_file_location("radarr_rules", ROOT / "radarr.py")
    radarr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(radarr)

HASH = "E43AE60250A49EF49474395D43962EBDA00809F3"
PATH = "/data/media/movies/The Odyssey (2026) {tmdb-1368337}/The Odyssey.mkv"


def movie(run_time="1:26:03", runtime=173, available=False):
    return {"id": 461, "title": "The Odyssey", "year": 2026, "runtime": runtime, "isAvailable": available,
            "movieFile": {"id": 802, "path": PATH, "relativePath": "The Odyssey.mkv",
                          "dateAdded": "2026-10-30T23:46:00Z", "mediaInfo": {"runTime": run_time}}}


def history(imported_path=PATH, imported_at="2026-10-30T23:46:00Z", grabbed=True):
    events = [{"id": 1921, "eventType": "downloadFolderImported", "date": imported_at, "downloadId": HASH,
               "data": {"importedPath": imported_path}}]
    if grabbed:
        events.append({"id": 1920, "eventType": "grabbed", "date": "2026-10-30T23:43:44Z", "downloadId": HASH,
                       "data": {}})
    return events


class RuntimeGuardTests(unittest.TestCase):
    def app(self, movies, events=()):
        app = radarr.App()
        app.qbit = Mock()
        app.api = Mock(side_effect=lambda path, *args: (
            movies if path == "/movie" else list(events) if path.startswith("/history/movie") else
            {"records": []} if path.startswith("/queue") else [] if not args else None
        ))
        return app

    def mutations(self, app):
        return [c.args for c in app.api.call_args_list if len(c.args) > 1]

    def test_minutes_parses_radarr_run_times(self):
        self.assertAlmostEqual(radarr.minutes("1:26:03"), 86.05)
        self.assertAlmostEqual(radarr.minutes("26:30"), 26.5)
        for blank in (None, "", "n/a"):
            self.assertIsNone(radarr.minutes(blank))

    def test_short_unreleased_movie_is_rejected_without_searching(self):
        app = self.app([movie()], history())
        with patch.object(radarr, "DRY", False):
            actions, ask = app.check_library()
        self.assertEqual(self.mutations(app), [("/history/failed/1920", "POST", {}), ("/moviefile/802", "DELETE")])
        app.qbit.delete.assert_called_once_with(HASH)
        self.assertEqual(ask, {})
        self.assertIn("search waits for release", actions[0])

    def test_short_available_movie_is_rejected_and_searched(self):
        app = self.app([movie(available=True)], history())
        with patch.object(radarr, "DRY", False):
            actions, _ = app.check_library()
        self.assertEqual(self.mutations(app)[-1], ("/command", "POST", {"name": "MoviesSearch", "movieIds": [461]}))
        self.assertIn("re-searching", actions[0])

    def test_renamed_file_matches_import_by_date(self):
        app = self.app([movie()], history(imported_path="/old/name.mkv", imported_at="2026-10-30T23:45:58Z"))
        with patch.object(radarr, "DRY", False):
            app.check_library()
        self.assertIn(("/history/failed/1920", "POST", {}), self.mutations(app))

    def test_without_a_grab_it_alerts_instead_of_deleting(self):
        for events in ([], history(grabbed=False), history(imported_path="/x.mkv", imported_at="2026-01-01T00:00:00Z")):
            with self.subTest(events=events):
                app = self.app([movie()], events)
                with patch.object(radarr, "DRY", False):
                    actions, ask = app.check_library()
                self.assertEqual((actions, self.mutations(app)), ([], []))
                app.qbit.delete.assert_not_called()
                self.assertIn("short:802", ask)

    def test_normal_or_unknown_runtimes_are_left_alone(self):
        cases = [movie(run_time="2:52:40"), movie(run_time="2:01:30"), movie(run_time=""),
                 movie(run_time="0:00:00"), movie(runtime=0), {"id": 1, "runtime": 120, "movieFile": None}]
        app = self.app(cases, history())
        with patch.object(radarr, "DRY", False):
            self.assertEqual(app.check_library(), ([], {}))
        self.assertEqual(self.mutations(app), [])

    def test_dry_run_only_reports(self):
        app = self.app([movie()], history())
        with patch.object(radarr, "DRY", True):
            actions, _ = app.check_library()
        self.assertEqual(self.mutations(app), [])
        app.qbit.delete.assert_not_called()
        self.assertTrue(actions[0].startswith("DRY would reject"))

    def test_qbit_delete_only_sends_torrent_hashes(self):
        q = engine.Qbit.__new__(engine.Qbit)
        q.post = Mock()
        q.delete("SABnzbd_nzo_abc123")
        q.delete(None)
        q.post.assert_not_called()
        q.delete(HASH)
        q.post.assert_called_once_with("torrents/delete", {"hashes": HASH.lower(), "deleteFiles": "true"})

    def test_other_apps_have_no_library_rules(self):
        self.assertEqual(engine.Arr().check_library(), ([], {}))

    def test_run_reports_library_actions(self):
        app = self.app([movie()], history())
        app.qbit = None
        app.missing_hours = 0
        with patch.object(engine, "DRY", False), patch.object(radarr, "DRY", False), \
                patch.object(engine, "QBIT_USER", ""), \
                patch.object(engine, "load_state", side_effect=lambda name, default: default), \
                patch.object(engine, "save_state"), patch.object(engine, "log") as log:
            app.run()
        self.assertTrue(any("blocklisted, deleted" in str(c.args) for c in log.call_args_list))


class FakeApp(engine.Arr):
    name = "Fake"
    media_id = "mediaId"
    media = "thing"
    category_field = "musicCategory"
    tag = "musical_note"

    def fix_import(self, rows, torrent):
        return None, "needs a human"


class StopLoop(Exception):
    pass


class AlertTests(unittest.TestCase):
    def test_clean_unescapes_html_entities(self):
        self.assertEqual(engine.clean("Ti&euml;sto &amp; Co &ndash; &quot;On My Way&quot; &rsquo;"), "Tiësto & Co – \"On My Way\" ’")
        self.assertEqual((engine.clean(None), engine.clean("plain & simple")), ("", "plain & simple"))
        self.assertEqual(engine.Arr().label([{"title": "Rock &amp; Roll"}]), "Rock & Roll")

    def test_needs_attention_alert_does_not_expose_details(self):
        def row(i, title, media_id, state, status, messages=()):
            return {"id": i, "downloadId": f"d{i}", "title": title, "mediaId": media_id, "protocol": "torrent",
                    "trackedDownloadState": state, "trackedDownloadStatus": status,
                    "statusMessages": [{"title": m, "messages": []} for m in messages]}

        rows = [row(1, "Ti&euml;sto &amp; Friends &ndash; On My Way", 5, "importFailed", "warning"),
                row(2, "Unmatched &amp; Co", None, "importFailed", "warning", ["Rock &amp; Roll", "Artist &quot;X&quot;"]),
                row(3, "Healthy", 7, "downloading", "ok")]
        torrents = [{"hash": "D3", "name": "Matched &amp; Co", "state": "stalledDL", "progress": 0.01, "num_seeds": 0, "added_on": 0},
                    {"hash": "FFF", "name": "CloZee &ndash; Koto &amp; More", "state": "stalledDL", "progress": 0.01, "num_seeds": 0,
                     "added_on": 0}]
        qbit = Mock()
        qbit.torrents.return_value = torrents
        app = FakeApp()
        app.connect_qbit = Mock(return_value=qbit)
        app.api = Mock(side_effect=lambda path, *args: (
            {"records": rows} if path.startswith("/queue") else
            [{"implementation": "QBittorrent", "fields": [{"name": "musicCategory", "value": "music"}]}]
            if path == "/downloadclient" else []))
        with patch.object(engine, "DRY", False), patch.object(engine, "GRACE", 0), patch.object(engine, "QBIT_USER", "user"), \
                patch.object(engine, "load_state", side_effect=lambda name, default: default), \
                patch.object(engine, "save_state"), patch.object(engine, "log") as log, patch.object(engine, "ntfy") as ntfy:
            app.run()
        title, body = ntfy.call_args.args[:2]
        self.assertEqual(title, "Fake: needs attention")
        self.assertEqual(body, "3 item(s) need attention; see the maintenance logs.")
        logged = [c.args for c in log.call_args_list]
        self.assertIn(("ACTION:", "dead torrent (stalledDL, 1%) -> blocklisted: Matched & Co"), logged)
        self.assertNotRegex(" ".join(map(str, logged)), r"&[a-z]+;")

    def failing_main(self, outcomes, alert_cycles=2):
        """Runs main() through `outcomes` (an exception to fail a run, None to pass); returns the ntfy mock."""
        app = Mock()
        app.name, app.tag = "Lidarr", "musical_note"
        app.run.side_effect = outcomes
        module = Mock()
        module.App.return_value = app
        sleeps = iter([None] * (len(outcomes) - 1) + [StopLoop()])

        def sleep(_):
            step = next(sleeps)
            if step:
                raise step

        state = {}
        with patch.dict(os.environ, {"APP": "lidarr"}), patch.object(engine.importlib, "import_module", return_value=module), \
                patch.object(engine.os, "makedirs"), patch.object(engine.time, "sleep", side_effect=sleep), \
                patch.object(engine, "DRY", False), patch.object(engine, "ONCE", False), \
                patch.object(engine, "FAIL_ALERT_CYCLES", alert_cycles), patch.object(engine, "log"), \
                patch.object(engine, "load_state", side_effect=lambda name, default: state.get(name, default)), \
                patch.object(engine, "save_state", side_effect=state.__setitem__), patch.object(engine, "ntfy") as ntfy:
            with self.assertRaises(StopLoop):
                engine.main()
        return ntfy, state

    def test_one_failed_run_is_not_alerted(self):
        refused = ConnectionRefusedError("[Errno 111] Connection refused")
        for outcomes in ([refused, None, None], [refused, None, refused, None], [None, refused]):
            with self.subTest(outcomes=outcomes):
                ntfy, state = self.failing_main(outcomes)
                ntfy.assert_not_called()
                self.assertNotIn("last_error.json", state)

    def test_consecutive_failed_runs_alert_once(self):
        refused = ConnectionRefusedError("[Errno 111] Connection refused")
        ntfy, state = self.failing_main([refused, None, refused, refused, refused, refused])
        ntfy.assert_called_once_with("Lidarr maintenance: run failed", "ConnectionRefusedError; see the maintenance logs.",
                                     "high", "musical_note,rotating_light")
        self.assertEqual(state["last_error.json"]["msg"], "ConnectionRefusedError: [Errno 111] Connection refused")

    def test_alert_cycles_can_be_one_to_alert_at_once(self):
        ntfy, _ = self.failing_main([RuntimeError("boom")], alert_cycles=1)
        ntfy.assert_called_once()

    def test_changed_or_old_errors_alert_again(self):
        app = Mock()
        app.name, app.tag = "Lidarr", "musical_note"
        state = {}
        with patch.object(engine, "DRY", False), patch.object(engine, "FAIL_ALERT_CYCLES", 2), \
                patch.object(engine, "load_state", side_effect=lambda name, default: state.get(name, default)), \
                patch.object(engine, "save_state", side_effect=state.__setitem__), patch.object(engine, "ntfy") as ntfy:
            engine.report_failure(app, RuntimeError("one"), 2)
            engine.report_failure(app, RuntimeError("one"), 3)
            self.assertEqual(ntfy.call_count, 1)
            engine.report_failure(app, RuntimeError("two"), 4)
            self.assertEqual(ntfy.call_count, 2)
            state["last_error.json"]["at"] -= 7 * 3600
            engine.report_failure(app, RuntimeError("two"), 5)
            self.assertEqual(ntfy.call_count, 3)


if __name__ == "__main__":
    unittest.main()
