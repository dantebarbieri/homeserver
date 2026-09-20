import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docker/scripts/reconcile-docker-socket-consumers.sh"
SERVICES = ("homepage", "alloy", "cadvisor", "vpn-netns-watcher")

MOCK_DOCKER = r"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps({"tool": "docker", "args": args, "cwd": os.getcwd()}) + "\n")
if args[0] == "ps":
    service = next(
        value.removeprefix("label=com.docker.compose.service=")
        for value in args
        if value.startswith("label=com.docker.compose.service=")
    )
    if service == os.environ.get("FAIL_ENUMERATION"):
        sys.exit(42)
    if service in json.loads(os.environ["RUNNING_SERVICES"]):
        print("container-id-" + service)
elif args[0] == "compose":
    if args[-1] == os.environ.get("FAIL_RECREATE"):
        sys.exit(43)
else:
    sys.exit("Unexpected Docker command")
"""

MOCK_FLOCK = r"""#!/usr/bin/env python3
import json
import os
import sys

os.fstat(9)
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps({"tool": "flock", "args": sys.argv[1:]}) + "\n")
sys.exit(int(os.environ.get("FAIL_LOCK", "0")))
"""


class ReconcileDockerSocketConsumersTests(unittest.TestCase):
    def setUp(self):
        # Keep all generated fixtures inside the checkout, never in a system temp directory.
        self.workspace = ROOT / "docker/tests" / (".socket-refresh-test-" + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, self.workspace)
        self.bin_dir = self.workspace / "bin"
        self.compose_dir = self.workspace / "compose"
        self.bin_dir.mkdir(parents=True)
        self.compose_dir.mkdir()
        (self.compose_dir / "docker-compose.yml").write_text("name: compose\nservices: {}\n")
        self.call_log = self.workspace / "calls.jsonl"
        for name, content in (("docker", MOCK_DOCKER), ("flock", MOCK_FLOCK)):
            executable = self.bin_dir / name
            executable.write_text(content)
            executable.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(self.bin_dir) + os.pathsep + os.environ["PATH"],
            "COMPOSE_DIR": str(self.compose_dir),
            "COMPOSE_LOCK_FILE": str(self.workspace / "compose.lock"),
            "CALL_LOG": str(self.call_log),
            "RUNNING_SERVICES": "[]",
        }
        for key in ("FAIL_ENUMERATION", "FAIL_RECREATE", "FAIL_LOCK"):
            self.env.pop(key, None)

    def run_script(self, running=(), **overrides):
        env = {**self.env, "RUNNING_SERVICES": json.dumps(running), **overrides}
        result = subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=15
        )
        calls = (
            [json.loads(line) for line in self.call_log.read_text().splitlines()]
            if self.call_log.exists()
            else []
        )
        return result, calls

    def assert_enumeration(self, call, service):
        self.assertEqual(
            call["args"],
            [
                "ps",
                "--filter", "status=running",
                "--filter", "label=com.docker.compose.project=compose",
                "--filter", "label=com.docker.compose.service=" + service,
                "--filter", "label=com.docker.compose.oneoff=False",
                "--format", "{{.ID}}",
            ],
        )

    def assert_recreate(self, call, service):
        self.assertEqual(call["cwd"], str(self.compose_dir))
        self.assertEqual(
            call["args"],
            [
                "compose",
                "--project-name", "compose",
                "--project-directory", str(self.compose_dir),
                "--file", str(self.compose_dir / "docker-compose.yml"),
                "up", "--no-deps", "--force-recreate", "--pull", "never",
                "--no-build", "-d", service,
            ],
        )

    def test_all_running_services_are_refreshed_serially_after_lock(self):
        result, calls = self.run_script(SERVICES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls[0], {"tool": "flock", "args": ["--exclusive", "--timeout", "600", "9"]}
        )
        self.assertEqual(len(calls), 9)
        for index, service in enumerate(SERVICES):
            self.assert_enumeration(calls[1 + index * 2], service)
            self.assert_recreate(calls[2 + index * 2], service)

    def test_stopped_absent_and_unrelated_services_are_not_started(self):
        result, calls = self.run_script(("alloy", "vpn-netns-watcher", "plex", "homepage-extra"))
        self.assertEqual(result.returncode, 0, result.stderr)
        recreated = [call for call in calls if call["args"][0] == "compose"]
        self.assertEqual(len(recreated), 2)
        self.assert_recreate(recreated[0], "alloy")
        self.assert_recreate(recreated[1], "vpn-netns-watcher")
        self.assertIn("Skipping homepage", result.stdout)
        self.assertIn("Skipping cadvisor", result.stdout)

    def test_no_running_consumers_is_a_successful_noop(self):
        result, calls = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 5)
        for call, service in zip(calls[1:], SERVICES):
            self.assert_enumeration(call, service)
        self.assertNotIn("Refreshing", result.stdout)

    def test_enumeration_failure_is_not_treated_as_no_running_container(self):
        result, calls = self.run_script(SERVICES, FAIL_ENUMERATION="homepage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot enumerate running containers for homepage", result.stderr)
        self.assertEqual(len(calls), 2)

    def test_recreation_failure_stops_and_reports_partial_progress(self):
        result, calls = self.run_script(SERVICES, FAIL_RECREATE="alloy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recreation failed for alloy", result.stderr)
        self.assertIn("remaining services were not attempted", result.stderr)
        self.assertEqual(len(calls), 5)
        self.assert_recreate(calls[2], "homepage")
        self.assert_recreate(calls[4], "alloy")

    def test_lock_failure_prevents_any_docker_command(self):
        result, calls = self.run_script(SERVICES, FAIL_LOCK="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not acquire Compose lock", result.stderr)
        self.assertEqual([call["tool"] for call in calls], ["flock"])

    def test_missing_main_compose_file_fails_before_docker(self):
        (self.compose_dir / "docker-compose.yml").unlink()
        result, calls = self.run_script(SERVICES)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read", result.stderr)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
