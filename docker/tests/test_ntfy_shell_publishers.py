import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "bmc": (ROOT / "dockerfiles/bmc-monitor/bmc-ip-monitor.sh", "\nnpm_login()"),
    "qbit": (ROOT / "dockerfiles/port-sync/port-sync.sh", "\nAPI_FAIL_COUNT=0"),
    "slskd": (ROOT / "dockerfiles/slskd-port-sync/slskd-port-sync.sh", "\napi()"),
}
HELPER = ROOT / "scripts/ntfy-curl.sh"
OUTBOX = ROOT / "scripts/ntfy-outbox.sh"
SH = shutil.which("sh")


def shell_path(path):
    if os.name != "nt":
        return str(path)
    return subprocess.check_output([SH, "-c", 'cygpath -u "$1"', "sh", str(path)], text=True).strip()


def windows_sync_stub(root):
    if os.name == "nt":
        sync = root / "sync"
        sync.write_text("#!/bin/sh\nexit 0\n")
        sync.chmod(0o755)


@unittest.skipUnless(SH, "shell publisher tests require sh")
class ShellPublisherTests(unittest.TestCase):
    def test_authenticated_send_and_http_failure(self):
        for name, (path, boundary) in SCRIPTS.items():
            for status, http_status in ((0, "200"), (22, "500"), (0, "302")):
                with self.subTest(publisher=name, status=status, http_status=http_status), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    windows_sync_stub(root)
                    prefix = path.read_text().split(boundary, 1)[0]
                    prefix = prefix.replace("/usr/local/lib/ntfy-curl.sh", shlex.quote(shell_path(HELPER)))
                    prefix = prefix.replace("/usr/local/lib/ntfy-outbox.sh", shlex.quote(shell_path(OUTBOX)))
                    prefix = f"PATH={shlex.quote(shell_path(root))}:$PATH\n" + prefix
                    token = root / "token"
                    token.write_text("tk_testpublisher\n")
                    queue = root / "outbox"
                    queue.mkdir()
                    curl = root / "curl"
                    curl.write_text(
                        '#!/bin/sh\ncat > "$CURL_CONFIG"\nprintf "%s\\n" "$*" > "$CURL_ARGS"\n'
                        'printf "%s" "$CURL_HTTP_STATUS"\nexit "$CURL_STATUS"\n'
                    )
                    curl.chmod(0o755)
                    env = {
                        **os.environ,
                        "NTFY_TOKEN_FILE": shell_path(token),
                        "NTFY_OUTBOX": shell_path(queue),
                        "NTFY_URL": "http://ntfy.invalid",
                        "NTFY_TOPIC": "alerts",
                        "CURL_CONFIG": shell_path(root / "config"),
                        "CURL_ARGS": shell_path(root / "args"),
                        "CURL_STATUS": str(status),
                        "CURL_HTTP_STATUS": http_status,
                        "NPM_HOST": "npm",
                        "NPM_PORT": "81",
                    }
                    result = subprocess.run(
                        [SH, "-c", prefix + '\nntfy "Title" "Message"\n'],
                        env=env, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / "config").read_text(),
                                     'header = "Authorization: Bearer tk_testpublisher"\n')
                    args = (root / "args").read_text()
                    self.assertIn("--fail", args)
                    self.assertIn("Title: Title", args)
                    self.assertNotIn("tk_testpublisher", args + result.stdout + result.stderr)
                    failed = status != 0 or http_status != "200"
                    self.assertEqual("ntfy send failed" in result.stdout, failed)
                    self.assertEqual(len(list(queue.glob("*.alert"))), int(failed))
                    if failed:
                        env["CURL_STATUS"] = "0"
                        env["CURL_HTTP_STATUS"] = "200"
                        retried = subprocess.run([SH, "-c", prefix + "\nntfy_outbox_flush\n"],
                                                 env=env, capture_output=True, text=True)
                        self.assertEqual(retried.returncode, 0, retried.stderr)
                        self.assertEqual(list(queue.glob("*.alert")), [])

    def test_restored_port_alert_is_retried_after_queue_failure(self):
        boundaries = {"qbit": "\n    # Login", "slskd": '\n  CURRENT='}
        for name, end in boundaries.items():
            path, _ = SCRIPTS[name]
            script = path.read_text()
            start = script.index('if [ "$PORT_ALERTED" -eq 1 ]; then')
            recovery = script[start:script.index(end, start)]
            program = (
                'PORT_ALERTED=1; PORT_MISSING_COUNT=5; PORT=1234\n'
                'ntfy() { return "$QUEUE_STATUS"; }\n'
                'QUEUE_STATUS=1\n' + recovery + '\n'
                '[ "$PORT_ALERTED" -eq 1 ] || exit 1\n'
                'QUEUE_STATUS=0\n' + recovery + '\n'
                '[ "$PORT_ALERTED" -eq 0 ] || exit 1\n'
            )
            with self.subTest(publisher=name):
                result = subprocess.run([SH, "-c", program], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_bmc_ip_changes_retry_after_queue_failure(self):
        path, boundary = SCRIPTS["bmc"]
        prefix = path.read_text().split(boundary, 1)[0]
        prefix = prefix.replace("/usr/local/lib/ntfy-curl.sh", shlex.quote(shell_path(HELPER)))
        prefix = prefix.replace("/usr/local/lib/ntfy-outbox.sh", shlex.quote(shell_path(OUTBOX)))
        program = (
            prefix + '\n'
            'ntfy() { [ "$QUEUE_STATUS" = 0 ] || return 1; printf "%s\\n" "$2"; }\n'
            'QUEUE_STATUS=1\n'
            'notify_ip_change first\nnotify_ip_change second\nretry_ip_changes\n'
            '[ -n "$PENDING_IP_CHANGES" ] || exit 1\n'
            'QUEUE_STATUS=0\nretry_ip_changes\n'
            '[ -z "$PENDING_IP_CHANGES" ] || exit 1\n'
        )
        result = subprocess.run([SH, "-c", program],
                                env={**os.environ, "NPM_HOST": "npm", "NPM_PORT": "81"},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "first\nsecond\n")

    def test_queue_sync_failure_is_reported(self):
        for fail_directory in (False, True):
            with self.subTest(fail_directory=fail_directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                sync = root / "sync"
                sync.write_text('#!/bin/sh\nfor last do :; done\n'
                                '[ "$last" != "$SYNC_FAIL" ]\n')
                sync.chmod(0o755)
                queue = root / "outbox"
                queue.mkdir()
                path, boundary = SCRIPTS["bmc"]
                prefix = path.read_text().split(boundary, 1)[0]
                prefix = prefix.replace("/usr/local/lib/ntfy-curl.sh", shlex.quote(shell_path(HELPER)))
                prefix = prefix.replace("/usr/local/lib/ntfy-outbox.sh", shlex.quote(shell_path(OUTBOX)))
                prefix = f"PATH={shlex.quote(shell_path(root))}:$PATH\n" + prefix
                env = {**os.environ, "NPM_HOST": "npm", "NPM_PORT": "81",
                       "NTFY_OUTBOX": shell_path(queue),
                       "SYNC_FAIL": shell_path(queue) if fail_directory else ""}
                if not fail_directory:
                    sync.write_text("#!/bin/sh\nexit 1\n")
                result = subprocess.run([SH, "-c", prefix + '\nntfy "Title" "Message"\n'],
                                        env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("alert could not be queued", result.stdout)
                self.assertEqual(len(list(queue.glob("*.alert"))), int(fail_directory))

    def test_real_http_redirect_is_not_treated_as_delivery(self):
        if subprocess.run([SH, "-c", "command -v curl >/dev/null"]).returncode:
            self.skipTest("curl is unavailable")
        requests = []

        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                windows_sync_stub(root)
                token = root / "token"
                token.write_text("tk_testpublisher\n")
                queue = root / "outbox"
                queue.mkdir()
                path, boundary = SCRIPTS["bmc"]
                prefix = path.read_text().split(boundary, 1)[0]
                prefix = prefix.replace("/usr/local/lib/ntfy-curl.sh", shlex.quote(shell_path(HELPER)))
                prefix = prefix.replace("/usr/local/lib/ntfy-outbox.sh", shlex.quote(shell_path(OUTBOX)))
                prefix = f"PATH={shlex.quote(shell_path(root))}:$PATH\n" + prefix
                env = {**os.environ, "NPM_HOST": "npm", "NPM_PORT": "81",
                       "NTFY_TOKEN_FILE": shell_path(token), "NTFY_OUTBOX": shell_path(queue),
                       "NTFY_URL": f"http://127.0.0.1:{server.server_port}", "NTFY_TOPIC": "alerts"}
                result = subprocess.run([SH, "-c", prefix + '\nntfy "Title" "Message"\n'],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(list(queue.glob("*.alert"))), 1)
                self.assertEqual(requests, ["/alerts"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
