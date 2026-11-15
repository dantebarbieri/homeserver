import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "macos/start-tdarr.sh"
BASH = shutil.which("bash")
PERL = shutil.which("perl")


def helpers(listing="/bin/ls"):
    """The Studio start script's probe helpers, pointed at this host's perl."""
    text = SCRIPT.read_text()
    functions = []
    for name in ("bounded", "is_mount", "share_healthy"):
        match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
        assert match, f"{name} is missing from {SCRIPT.name}"
        functions.append(match.group(0))
    script = "\n".join(functions).replace("/usr/bin/perl", shlex.quote(PERL))
    return script.replace("/bin/ls", shlex.quote(listing))


@unittest.skipUnless(BASH and PERL and os.name == "posix", "needs bash and perl on a POSIX system")
class StudioStartTdarrProbeTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / "docker/tests" / (".studio-start-test-" + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, self.workspace)
        (self.workspace / "mounts/plain").mkdir(parents=True)
        # /dev is a separate filesystem on Linux and macOS, so it stands in for a mount.
        (self.workspace / "mounts/dev").symlink_to("/dev")

    def run_shell(self, body, listing="/bin/ls"):
        started = time.monotonic()
        result = subprocess.run(
            [BASH, "-c", helpers(listing) + "\n" + body],
            env={**os.environ, "HOME": str(self.workspace)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result, time.monotonic() - started

    def test_passes_the_probe_status_and_output_through(self):
        result, _ = self.run_shell("bounded 5 sh -c 'echo hi; exit 7'")
        self.assertEqual((result.returncode, result.stdout), (7, "hi\n"))

    def test_reports_a_missing_program_as_127(self):
        result, _ = self.run_shell("bounded 5 /nonexistent/probe")
        self.assertEqual(result.returncode, 127)

    def test_kills_a_probe_that_ignores_sigterm_at_the_deadline(self):
        result, elapsed = self.run_shell("bounded 1 sh -c 'trap \"\" TERM; sleep 30'")
        self.assertEqual(result.returncode, 124)
        self.assertLess(elapsed, 10)

    def test_kills_what_the_probe_started_so_command_substitution_cannot_stall(self):
        result, elapsed = self.run_shell(
            "out=$(bounded 1 sh -c 'sleep 30 & echo hi; wait'); echo \"rc=$? out=$out\""
        )
        self.assertEqual(result.stdout, "rc=124 out=hi\n")
        self.assertLess(elapsed, 10)

    def test_tells_a_mount_from_a_plain_directory(self):
        result, _ = self.run_shell(
            """
            for name in dev plain absent; do
                rc=0; is_mount "$HOME/mounts/$name" || rc=$?
                echo "$name=$rc"
            done
            share_healthy dev && echo healthy-dev
            share_healthy plain || echo unhealthy-plain
            """
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["dev=0", "plain=1", "absent=2", "healthy-dev", "unhealthy-plain"],
        )

    def test_a_mount_that_cannot_be_listed_is_unhealthy(self):
        failing = self.workspace / "ls-fails"
        failing.write_text("#!/bin/sh\nexit 5\n")
        failing.chmod(0o755)
        result, _ = self.run_shell("share_healthy dev || echo unhealthy-dev", listing=str(failing))
        self.assertEqual(result.stdout, "unhealthy-dev\n")


if __name__ == "__main__":
    unittest.main()
