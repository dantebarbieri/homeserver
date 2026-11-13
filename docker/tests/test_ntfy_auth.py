import importlib.util
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auth = load("ntfy_auth", ROOT / "scripts/ntfy_auth.py")
arr = load("arr_maint", ROOT / "dockerfiles/arr-maint/arr_maint.py")


class NtfyAuthTests(unittest.TestCase):
    def test_publisher_headers_require_valid_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            for value in ("", "not-a-token", "tk_bad\ninjected"):
                path.write_text(value)
                with self.subTest(value=value), patch.dict(os.environ, {"NTFY_TOKEN_FILE": str(path)}):
                    with self.assertRaises(ValueError):
                        auth.publisher_headers()
            path.write_text("tk_testpublisher\n")
            with patch.dict(os.environ, {"NTFY_TOKEN_FILE": str(path)}):
                self.assertEqual(auth.publisher_headers(), {"Authorization": "Bearer tk_testpublisher"})

    def test_outbox_retries_persisted_alert_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token"
            token.write_text("tk_testpublisher\n")
            with patch.dict(os.environ, {"NTFY_TOKEN_FILE": str(token)}), \
                    patch.object(auth._opener, "open") as send:
                outbox = auth.Outbox(tmp, "http://ntfy.invalid", "alerts")
                send.side_effect = HTTPError("http://ntfy.invalid", 403, "Forbidden", {}, None)
                outbox.submit("Title", "Message")
                outbox.submit("Second", "Second message")
                queued = list(outbox.directory.glob("*.json"))
                self.assertEqual(len(queued), 2)
                self.assertNotIn("tk_testpublisher", queued[0].read_text())
                token.unlink()
                restarted = auth.Outbox(tmp, "http://ntfy.invalid", "alerts")
                self.assertFalse(restarted.flush())
                self.assertEqual(len(list(restarted.directory.glob("*.json"))), 2)
                token.write_text("tk_testpublisher\n")
                send.side_effect = None
                send.reset_mock()
                self.assertTrue(restarted.flush())
                self.assertEqual(send.call_args_list[0].args[0].get_header("Authorization"),
                                 "Bearer tk_testpublisher")
                self.assertEqual([call.args[0].data for call in send.call_args_list],
                                 [b"Message", b"Second message"])
                self.assertEqual(list(restarted.directory.glob("*.json")), [])

    def test_outbox_does_not_forward_publisher_token_on_redirect(self):
        requests = []

        class Destination(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/capture")
                self.end_headers()

            def log_message(self, *_):
                pass

        source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        for server in (source, destination):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "token"
            token.write_text("tk_testpublisher\n")
            with patch.dict(os.environ, {"NTFY_TOKEN_FILE": str(token)}):
                outbox = auth.Outbox(tmp, f"http://127.0.0.1:{source.server_port}", "alerts")
                outbox.submit("Title", "Message")
                self.assertEqual(requests, [])
                self.assertEqual(len(list(outbox.directory.glob("*.json"))), 1)

    def test_outbox_worker_starts_once(self):
        with patch.object(auth, "_outbox", None), patch.object(auth, "Outbox") as make:
            first = auth.start_outbox("/state", "http://ntfy.invalid", "alerts")
            second = auth.start_outbox("/state", "http://ntfy.invalid", "alerts")
            self.assertIs(first, second)
            make.assert_called_once_with("/state", "http://ntfy.invalid", "alerts")
            first.start.assert_called_once_with()

    def test_publishers_enqueue_and_report_queue_failure(self):
        plex = load("plex_sync_ntfy", ROOT / "dockerfiles/plex-navidrome-sync/plex_navidrome_sync.py")
        cover = load("cover_ntfy", ROOT / "dockerfiles/music-cover-fallback/music_cover_fallback.py")
        lyrics = load("lyrics_ntfy", ROOT / "dockerfiles/music-lyrics-fallback/music_lyrics_fallback.py")
        env = {"NTFY_URL": "http://ntfy.invalid", "NTFY_TOPIC": "alerts"}
        queue = Mock()
        with patch.dict(os.environ, env), patch.dict("sys.modules", {"ntfy_auth": auth}), \
                patch.object(auth, "start_outbox", return_value=queue), \
                patch.object(arr, "NTFY_URL", env["NTFY_URL"]), \
                patch.object(arr, "NTFY_TOPIC", env["NTFY_TOPIC"]), \
                patch.object(plex, "NTFY_URL", env["NTFY_URL"]), \
                patch.object(plex, "NTFY_TOPIC", env["NTFY_TOPIC"]):
            self.assertTrue(arr.ntfy("Title", "Message"))
            self.assertTrue(plex.ntfy("Title", "Message"))
            cover.notify("Title", "Message")
            lyrics.notify_failure()
            self.assertEqual(queue.submit.call_count, 4)
            queue.submit.side_effect = OSError("disk full")
            self.assertFalse(arr.ntfy("Title", "Message"))
            self.assertFalse(plex.ntfy("Title", "Message"))
            with self.assertRaises(OSError):
                cover.notify("Title", "Message")
            with self.assertRaises(OSError):
                lyrics.notify_failure()

    def test_arr_does_not_mark_failed_alerts_delivered(self):
        app = arr.Arr()
        app.name = "Radarr"
        app.api = Mock(return_value={"records": []})
        app.check_library = Mock(return_value=([], {"needs-help": "sensitive details"}))
        app.periodic = Mock(return_value=None)
        with patch.object(arr, "QBIT_USER", ""), patch.object(arr, "DRY", False), \
                patch.object(arr, "load_state", return_value={}), \
                patch.object(arr, "save_state") as save, \
                patch.object(arr, "ntfy", return_value=False) as notify:
            app.run()
            saved = dict(call.args for call in save.call_args_list)
            self.assertEqual(saved["notified.json"], {})
            self.assertNotIn("sensitive details", notify.call_args.args[1])
            save.reset_mock()
            arr.report_failure(app, RuntimeError("secret details"), arr.FAIL_ALERT_CYCLES)
            self.assertFalse(save.called)
            self.assertNotIn("secret details", notify.call_args.args[1])

    def test_sync_does_not_mark_failed_alert_delivered(self):
        plex = load("plex_sync_retry", ROOT / "dockerfiles/plex-navidrome-sync/plex_navidrome_sync.py")
        for delivered in (False, True):
            with self.subTest(delivered=delivered), \
                    patch.object(plex, "ONCE", True), patch.object(plex, "DRY", False), \
                    patch.object(plex, "configured", return_value=True), \
                    patch.object(plex.signal, "signal"), patch.object(plex.os, "makedirs"), \
                    patch.object(plex, "run", side_effect=RuntimeError("secret details")), \
                    patch.object(plex, "load_state", return_value={}), \
                    patch.object(plex, "save_state") as save, \
                    patch.object(plex, "ntfy", return_value=delivered) as notify, \
                    patch.object(plex, "log"):
                plex.main()
                self.assertEqual(save.called, delivered)
                self.assertNotIn("secret details", notify.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
