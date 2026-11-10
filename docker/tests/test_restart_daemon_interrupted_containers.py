import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "restart_interrupted", ROOT / "docker/scripts/restart-daemon-interrupted-containers.py"
)
restart = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restart)

# dockerd started 01:10:56 and reported ready at 01:14:17, like the Nov 10 rebuild.
DAEMON = (
    "ActiveState=active\n"
    "ExecMainStartTimestamp=Tue 2026-11-10 01:10:56.969501 UTC\n"
    "ActiveEnterTimestamp=Tue 2026-11-10 01:14:17.250000 UTC\n"
)
IN_WINDOW = "2026-11-10T01:11:00.123456789Z"
BEFORE = "2026-11-09T22:00:00.5Z"
AFTER = "2026-11-10T09:00:00Z"
LIVE = "sha256:live"


def container(name, policy="unless-stopped", finished=IN_WINDOW, running=False, network=None,
              depends=None, image="sha256:app", oneoff="False", healthcheck=False):
    labels = {
        "com.docker.compose.project": "compose",
        "com.docker.compose.service": name,
        "com.docker.compose.oneoff": oneoff,
    }
    if depends:
        labels["com.docker.compose.depends_on"] = depends
    state = {"Status": "running" if running else "exited", "Running": running,
             "ExitCode": 0, "FinishedAt": finished}
    if healthcheck:
        state["Health"] = {"Status": "healthy" if running else "unhealthy"}
    return {
        "Id": name + "-id", "Name": "/" + name, "Image": image,
        "Config": {"Labels": labels},
        "HostConfig": {"RestartPolicy": {"Name": policy},
                       "NetworkMode": f"container:{network}-id" if network else "compose_proxy"},
        "State": state,
    }


class FakeDocker:
    def __init__(self, *items, crash=()):
        self.containers = {item["Id"]: item for item in items}
        self.crash = set(crash)
        self.started = []
        self.starting = {}

    def __call__(self, *args, timeout=120):
        if args[:2] == ("systemctl", "show"):
            return DAEMON
        if args[:2] == ("docker", "ps"):
            # A started container reports healthy one listing after "starting".
            for identifier, listings in list(self.starting.items()):
                if listings:
                    self.containers[identifier]["State"]["Health"]["Status"] = "healthy"
                    del self.starting[identifier]
                else:
                    self.starting[identifier] = 1
            return "\n".join(self.containers) + "\n"
        if args[:2] == ("docker", "inspect"):
            return json.dumps([copy.deepcopy(self.containers[key]) for key in args[2:]])
        if args[:3] == ("docker", "image", "inspect"):
            return LIVE + "\n"
        if args[:2] == ("docker", "start"):
            item = self.containers[args[2]]
            self.started.append(item["Name"].lstrip("/"))
            if args[2] in self.crash:
                item["State"].update(ExitCode=1, FinishedAt=AFTER)
            else:
                item["State"].update(Status="running", Running=True)
                if "Health" in item["State"]:
                    item["State"]["Health"]["Status"] = "starting"
                    self.starting[args[2]] = 0
            return args[2] + "\n"
        raise AssertionError(f"unexpected command {args}")


class RestartDaemonInterruptedContainersTests(unittest.TestCase):
    def setUp(self):
        # Keep all generated fixtures inside the checkout, never in a system temp directory.
        self.workspace = ROOT / "docker/tests" / (".interrupted-test-" + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.hold = self.workspace / "hold"
        self.locks = 0
        self.alerts = []

        @contextlib.contextmanager
        def locked():
            self.locks += 1
            yield

        for name, value in (
            ("locked", locked), ("notify", lambda *alert: self.alerts.append(alert)),
            ("WIKI_BLOCKERS", (self.hold,)), ("POLL", 0),
        ):
            patcher = mock.patch.object(restart, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def main(self, docker, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(restart, "run", docker), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = restart.main(list(arguments))
        return code, stdout.getvalue() + stderr.getvalue()

    def test_only_containers_dockerd_stopped_while_starting_are_started(self):
        docker = FakeDocker(
            container("plex"),
            container("immich", policy="always"),
            container("operator-stopped", finished=AFTER),
            container("shutdown-stopped", finished=BEFORE),
            container("job", policy="no"),
            container("flaky", policy="on-failure"),
            container("compose-run", oneoff="True"),
            container("radarr", running=True),
        )
        code, output = self.main(docker)
        self.assertEqual(code, 0, output)
        self.assertEqual(docker.started, ["immich", "plex"])
        self.assertEqual(self.locks, 1)
        self.assertEqual(self.alerts[0][2], "default")
        self.assertIn("Started again: immich, plex", self.alerts[0][1])

    def test_dependencies_start_first_and_healthy_conditions_are_awaited(self):
        docker = FakeDocker(
            container("qbittorrent", network="gluetun", depends="gluetun:service_started:false"),
            container("gluetun", network="vpn-netns", depends="vpn-netns:service_started:false",
                      healthcheck=True),
            container("vpn-netns"),
            container("port-sync", depends="gluetun:service_healthy:true"),
        )
        code, output = self.main(docker)
        self.assertEqual(code, 0, output)
        self.assertEqual(docker.started, ["vpn-netns", "gluetun", "qbittorrent", "port-sync"])

    def test_wiki_frontend_starts_only_from_its_live_image_without_a_hold(self):
        code, output = self.main(FakeDocker(container("mirklurk", image=LIVE)))
        self.assertEqual(code, 0, output)
        for wiki, blocked in (
            (container("mirklurk", image="sha256:candidate"), "is not mirklurk-wiki:live"),
            (container("mirklurk", image=LIVE), "hold exists"),
        ):
            with self.subTest(blocked=blocked):
                if blocked == "hold exists":
                    self.workspace.mkdir()
                    self.hold.touch()
                docker = FakeDocker(wiki, container("plex"))
                self.alerts.clear()
                code, output = self.main(docker)
                self.assertEqual(code, 1, output)
                self.assertEqual(docker.started, ["plex"])
                self.assertEqual(self.alerts[0][2], "high")
                self.assertIn(blocked, self.alerts[0][1])

    def test_unsatisfiable_or_crashing_containers_are_reported(self):
        docker = FakeDocker(
            container("db", policy="no", finished=AFTER),
            container("app", depends="db:service_started:false"),
            container("orphan", network="gone"),
            container("crasher"),
            container("plex"),
            crash={"crasher-id"},
        )
        code, output = self.main(docker)
        self.assertEqual(code, 1, output)
        self.assertEqual(docker.started, ["crasher", "plex"])
        alert = self.alerts[0][1]
        self.assertIn("app: not started: dependency db is stopped", alert)
        self.assertIn("orphan: not started: network namespace container gone-id is missing", alert)
        self.assertIn("crasher: exited right after start (exit 1)", alert)
        self.assertIn("Started again: plex", alert)

    def test_nothing_to_do_and_dry_run_change_nothing(self):
        code, output = self.main(FakeDocker(container("plex", running=True)))
        self.assertEqual(code, 0, output)
        self.assertIn("No container was stopped by dockerd startup", output)
        docker = FakeDocker(container("plex"), container("mirklurk", image="sha256:old"))
        code, output = self.main(docker, "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertIn("Would start plex", output)
        self.assertIn("Would leave mirklurk stopped", output)
        self.assertEqual((docker.started, self.locks, self.alerts), ([], 0, []))


if __name__ == "__main__":
    unittest.main()
