import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "macos/start-tdarr.sh"
BASH = shutil.which("bash")
PERL = shutil.which("perl")


def function_text(name):
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SCRIPT.read_text(), re.M | re.S)
    assert match, f"{name} is missing from {SCRIPT.name}"
    return match.group(0)


def helpers(listing="/bin/ls"):
    """The Studio start script's probe helpers, pointed at this host's perl."""
    script = "\n".join(function_text(name) for name in ("bounded", "is_mount", "share_healthy"))
    script = script.replace("/usr/bin/perl", shlex.quote(PERL))
    return script.replace("/bin/ls", shlex.quote(listing))


# Stands in for everything the watchdog touches. Sleeping is instant but counted
# (naps), signals are recorded with the nap count at that moment, and the media
# probe follows the plan in $OUTCOMES: ok, fail, cache-fail (the cache probe
# fails this round), die-ok / die-fail (the node exits during the probe).
WATCHDOG_HARNESS = r"""
set -euo pipefail
naps="$HOME/naps" signals="$HOME/signals" probes="$HOME/probes"
: >"$naps"; : >"$signals"; : >"$probes"
read -r -a outcomes <<<"${OUTCOMES:-}"
round=0 cache_status=0

nap_count() { wc -l <"$naps" | tr -d ' '; }

# The node is another process that the test reaps, as its real parent would.
node_gone() { ! builtin kill -0 "$NODE" 2>/dev/null; }
end_node() {
    local i
    builtin kill -KILL "$NODE" 2>/dev/null || true
    for i in $(seq 500); do
        node_gone && return 0
        command sleep 0.01
    done
    return 1
}

fake_sleep() {
    echo "$1" >>"$naps"
    [[ "$(nap_count)" != "${KILL_ON_NAP:-0}" ]] || end_node
}

logged_kill() {
    local i
    if [[ "$1" == -0 ]]; then
        builtin kill "$@"
        return
    fi
    echo "${1#-} $2 $(nap_count)" >>"$signals"
    builtin kill "$@"
    for i in $(seq 100); do
        node_gone && return 0
        command sleep 0.01
    done
}

share_healthy() {
    local outcome status
    echo "$1" >>"$probes"
    if [[ "$1" == cache ]]; then
        status=$cache_status
        cache_status=0
        return "$status"
    fi
    outcome="${outcomes[$round]:-exhausted}"
    round=$((round + 1))
    case "$outcome" in
        ok) return 0 ;;
        fail) return 1 ;;
        cache-fail) cache_status=1; return 0 ;;
        die-ok) end_node; return 0 ;;
        die-fail) end_node; return 1 ;;
        *) echo "test plan ran out" >&2; end_node; return 1 ;;
    esac
}
"""


def watchdog_script():
    """The start script's watchdog, run against the stand-ins above."""
    functions = "\n".join(function_text(name) for name in ("alive", "nap", "watchdog"))
    functions = functions.replace("/bin/sleep", "fake_sleep").replace("/bin/kill", "logged_kill")
    return WATCHDOG_HARNESS + "\n" + functions + '\nwatchdog "$NODE"\n'


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


@unittest.skipUnless(BASH and os.name == "posix", "needs bash on a POSIX system")
class StudioStartTdarrWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / "docker/tests" / (".studio-start-test-" + uuid.uuid4().hex)
        self.workspace.mkdir()
        self.addCleanup(shutil.rmtree, self.workspace)
        self.nodes = []
        self.addCleanup(self.stop_nodes)

    def stop_nodes(self):
        for node in self.nodes:
            node.kill()
            node.wait()

    def start_node(self, ignores_term=False):
        """A long-lived process standing in for the node; a thread reaps it as its parent would."""
        ready = self.workspace / f"node-ready-{len(self.nodes)}"
        trap = 'trap "" TERM; ' if ignores_term else ""
        node = subprocess.Popen([BASH, "-c", f'{trap}echo >"$1"; exec sleep 300', "_", str(ready)])
        threading.Thread(target=node.wait, daemon=True).start()
        self.nodes.append(node)
        deadline = time.monotonic() + 10
        while not ready.exists():
            self.assertLess(time.monotonic(), deadline, "the node stand-in did not start")
            time.sleep(0.01)
        return node

    def run_watchdog(self, node, outcomes="", kill_on_nap=0):
        result = subprocess.run(
            [BASH, "-c", watchdog_script()],
            env={
                **os.environ,
                "HOME": str(self.workspace),
                "NODE": str(node.pid),
                "OUTCOMES": outcomes,
                "KILL_ON_NAP": str(kill_on_nap),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

        def lines(name):
            return (self.workspace / name).read_text().splitlines()

        return result, lines("naps"), lines("signals"), lines("probes")

    def test_ends_within_a_second_of_the_node_exiting(self):
        node = self.start_node()
        result, naps, signals, probes = self.run_watchdog(node, kill_on_nap=3)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        # One-second naps, and none after the node was gone: no minute-long wait, no check.
        self.assertEqual((naps, signals, probes), (["1"] * 3, [], []))

    def test_a_check_that_ends_after_the_node_exited_is_not_a_failure(self):
        for outcome in ("die-fail", "die-ok"):
            with self.subTest(outcome=outcome):
                node = self.start_node()
                result, naps, signals, probes = self.run_watchdog(node, outcome)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                # The first check comes after a minute, and the node's death ends the round.
                self.assertEqual((naps, signals, probes), (["1"] * 60, [], ["media"]))

    def test_three_failed_checks_in_a_row_stop_the_node_with_term(self):
        node = self.start_node()
        # A failing cache share counts like a failing media share.
        result, naps, signals, _ = self.run_watchdog(node, "fail cache-fail fail")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "Share health check failed (1 of 3).",
                "Share health check failed (2 of 3).",
                "Share health check failed (3 of 3).",
                "Stopping the node to remount the shares.",
            ],
        )
        # A check follows every minute of naps. The node gave way to TERM, so there is no KILL.
        self.assertEqual((signals, len(naps)), ([f"TERM {node.pid} 180"], 180))

    def test_a_good_check_starts_the_count_again(self):
        node = self.start_node()
        result, _, signals, _ = self.run_watchdog(node, "fail fail ok fail fail die-fail")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr.splitlines(),
            [f"Share health check failed ({count} of 3)." for count in (1, 2, 1, 2)],
        )
        self.assertEqual(signals, [])

    def test_a_node_that_exits_in_the_last_second_of_a_wait_is_not_acted_on(self):
        # The minute before a check: the node's exit ends the watchdog without a check.
        node = self.start_node()
        result, naps, signals, probes = self.run_watchdog(node, kill_on_nap=60)
        self.assertEqual((result.returncode, result.stderr, signals, probes), (0, "", [], []))
        self.assertEqual(len(naps), 60)
        # The grace after TERM: a node that goes at its end gets no KILL, because its
        # pid may belong to another process by now.
        node = self.start_node(ignores_term=True)
        result, naps, signals, _ = self.run_watchdog(node, "fail fail fail", kill_on_nap=200)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((signals, len(naps)), ([f"TERM {node.pid} 180"], 200))

    def test_a_node_that_ignores_term_is_killed_after_twenty_seconds(self):
        node = self.start_node(ignores_term=True)
        result, naps, signals, _ = self.run_watchdog(node, "fail fail fail")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(signals, [f"TERM {node.pid} 180", f"KILL {node.pid} 200"])
        self.assertEqual(node.wait(timeout=10), -signal.SIGKILL)
        self.assertEqual(naps, ["1"] * 200)


if __name__ == "__main__":
    unittest.main()
