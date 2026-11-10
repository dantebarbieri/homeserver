#!/usr/bin/env python3
"""Start the containers dockerd itself stopped while it was starting.

With live-restore disabled, a starting dockerd stops every container still
alive from before it: after dockerd crashes (systemd restarts it while the
container shims keep running) or on the first start after live-restore is
turned off. Docker records those stops as manual, so `unless-stopped` never
restarts them and `always` waits for the next daemon start. Containers that an
operator, Compose or a clean daemon shutdown stopped finish outside dockerd's
start-to-ready window and are never touched. The same containers are started
again in dependency order; nothing is recreated, pulled or rebuilt.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time


LOCK = Path(os.environ.get("COMPOSE_LOCK_FILE", "/run/lock/homeserver-compose.lock"))
LOCK_WAIT = 900
START_WAIT = 1200
POLL = 5
RESTART_POLICIES = {"always", "unless-stopped"}
# Restore records these exits before dockerd reports ready; allow for rounding.
SLACK = timedelta(seconds=1)
# The wiki frontend has its own release lifecycle (docker/docs/MIRKLURK.md):
# only its exact live image starts, and never during a hold or a snapshot.
WIKI_SERVICE = "mirklurk"
WIKI_LIVE_TAG = "mirklurk-wiki:live"
WIKI_BLOCKERS = (
    Path("/var/lib/mirklurk-auto-update/hold"),
    Path("/var/lib/mirklurk-upload-deployment/hold"),
    Path("/srv/docker/data/mirklurk/backup-control/read-only"),
)
PROJECT = "com.docker.compose.project"
SERVICE = "com.docker.compose.service"
ONEOFF = "com.docker.compose.oneoff"
DEPENDS_ON = "com.docker.compose.depends_on"


class Failure(Exception):
    pass


def run(*args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure(f"{' '.join(args[:2])} unavailable or timed out") from error
    # Inspect output holds container environments (secrets): report stderr only.
    if result.returncode != 0:
        raise Failure(f"{' '.join(args[:2])} failed (exit {result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout


def notify(title, message, priority, tags):
    try:
        subprocess.run(["ntfy-notify", title, message, priority, tags], timeout=180, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Alert was neither delivered nor queued: {error}", file=sys.stderr)


def systemd_time(value):
    match = re.fullmatch(r"\S+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(\d{1,6}))? UTC", value.strip())
    if not match:
        raise Failure(f"unexpected systemd timestamp {value!r}")
    moment = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return moment + timedelta(microseconds=int((match[2] or "0").ljust(6, "0")))


def docker_time(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)", value or "")
    if not match:
        return None
    moment = datetime.fromisoformat(match[1] + ("+00:00" if match[3] == "Z" else match[3]))
    return moment + timedelta(microseconds=int((match[2] or "0")[:6].ljust(6, "0")))


def daemon_window():
    """When the running dockerd started and when it reported ready."""
    output = run("systemctl", "show", "docker.service", "--timestamp=us+utc",
                 "--property=ActiveState,ExecMainStartTimestamp,ActiveEnterTimestamp")
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if values.get("ActiveState") != "active":
        raise Failure("docker.service is not active")
    start = systemd_time(values.get("ExecMainStartTimestamp", ""))
    ready = systemd_time(values.get("ActiveEnterTimestamp", ""))
    if ready < start:
        raise Failure("docker.service has not reported ready since its current process started")
    return start, ready


def containers():
    for attempt in range(3):
        try:
            ids = run("docker", "ps", "--all", "--quiet", "--no-trunc").split()
            return {item["Id"]: item for item in json.loads(run("docker", "inspect", *ids))} if ids else {}
        except Failure:
            # A container removed between the listing and inspect fails the call.
            if attempt == 2:
                raise
            time.sleep(POLL)


def name(container):
    return container["Name"].lstrip("/")


def labels(container):
    return container["Config"].get("Labels") or {}


def interrupted(container, start, ready):
    state = container["State"]
    finished = docker_time(state.get("FinishedAt"))
    return (
        (container["HostConfig"].get("RestartPolicy") or {}).get("Name") in RESTART_POLICIES
        and state.get("Status") == "exited"
        and labels(container).get(ONEOFF) != "True"
        and finished is not None and start <= finished <= ready + SLACK
    )


def wiki_refusal(container):
    if labels(container).get(SERVICE) != WIKI_SERVICE:
        return None
    for path in WIKI_BLOCKERS:
        if os.path.lexists(path):
            return f"{path} exists"
    try:
        live = run("docker", "image", "inspect", "--format", "{{.Id}}", WIKI_LIVE_TAG).strip()
    except Failure:
        return f"{WIKI_LIVE_TAG} cannot be inspected"
    if container["Image"] != live:
        return f"its image is not {WIKI_LIVE_TAG}"
    return None


def find(states, reference):
    for container in states.values():
        if reference in (container["Id"], name(container)):
            return container
    return None


def blocker(container, states, pending):
    """None when the container can start now, else (reason, worth waiting)."""
    def stopped(dependency, role):
        if dependency["Id"] in pending:
            return f"waiting for {name(dependency)}", True
        return f"{role} {name(dependency)} is stopped", False

    mode = container["HostConfig"].get("NetworkMode") or ""
    if mode.startswith("container:"):
        parent = find(states, mode.split(":", 1)[1])
        if parent is None:
            return f"network namespace container {mode.split(':', 1)[1][:12]} is missing", False
        if not parent["State"]["Running"]:
            return stopped(parent, "network namespace container")
    project = labels(container).get(PROJECT)
    for item in filter(None, (labels(container).get(DEPENDS_ON) or "").split(",")):
        service, condition = (item.split(":") + [""])[:2]
        dependencies = [
            other for other in states.values()
            if labels(other).get(PROJECT) == project and labels(other).get(SERVICE) == service
            and labels(other).get(ONEOFF) != "True"
        ]
        if not dependencies:
            return f"dependency {service} has no container", False
        for dependency in dependencies:
            state = dependency["State"]
            if condition == "service_completed_successfully":
                if state["Running"]:
                    return f"waiting for {name(dependency)} to complete", True
                if state.get("Status") != "exited" or state.get("ExitCode") != 0:
                    return f"dependency {name(dependency)} did not complete successfully", False
                continue
            if not state["Running"]:
                return stopped(dependency, "dependency")
            health = (state.get("Health") or {}).get("Status")
            if condition == "service_healthy" and health not in (None, "healthy"):
                return f"waiting for {name(dependency)} to become healthy", True
    return None


def restart(candidates):
    """Start candidates in dependency order. Returns (started, {name: problem})."""
    pending, launched = set(candidates), set()
    started, failed, waiting = [], {}, {}
    deadline = time.monotonic() + START_WAIT
    while pending:
        states = containers()
        launched_now = False
        waiting.clear()
        for identifier in sorted(pending, key=lambda key: name(states[key]) if key in states else key):
            container = states.get(identifier)
            if container is None:
                failed[identifier[:12]] = "container disappeared"
                pending.discard(identifier)
                continue
            if container["State"]["Running"]:
                if identifier in launched:
                    started.append(name(container))
                else:
                    print(f"{name(container)} is already running again; leaving it alone", flush=True)
                pending.discard(identifier)
                continue
            if identifier in launched:
                failed[name(container)] = f"exited right after start (exit {container['State'].get('ExitCode')})"
                pending.discard(identifier)
                continue
            reason = blocker(container, states, pending)
            if reason is None:
                print(f"Starting {name(container)}", flush=True)
                try:
                    run("docker", "start", identifier)
                except Failure as error:
                    failed[name(container)] = str(error)
                    pending.discard(identifier)
                else:
                    launched.add(identifier)
                    launched_now = True
            elif reason[1]:
                waiting[name(container)] = reason[0]
            else:
                failed[name(container)] = "not started: " + reason[0]
                pending.discard(identifier)
        if pending and not launched_now:
            if time.monotonic() >= deadline:
                for identifier in pending:
                    key = name(states[identifier]) if identifier in states else identifier[:12]
                    failed[key] = "timed out " + waiting.get(key, "waiting to start")
                break
            time.sleep(POLL)
    return started, failed


def select(start, ready):
    """{id: name} to start, plus {name: refusal} for those that must stay down."""
    selected, refused = {}, {}
    for identifier, container in sorted(containers().items(), key=lambda item: name(item[1])):
        if not interrupted(container, start, ready):
            continue
        refusal = wiki_refusal(container)
        if refusal:
            refused[name(container)] = f"not started: {refusal} (operator review: docker/docs/MIRKLURK.md)"
        else:
            selected[identifier] = name(container)
    return selected, refused


@contextmanager
def locked():
    import fcntl

    print(f"Waiting for Compose lock: {LOCK}", flush=True)
    descriptor = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Failure(f"could not acquire the Compose lock within {LOCK_WAIT} seconds") from None
                time.sleep(1)
        yield
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only list what would be started")
    arguments = parser.parse_args(argv)
    try:
        start, ready = daemon_window()
        window = f"{start:%Y-%m-%d %H:%M:%S} to {ready:%H:%M:%S} UTC"
        selected, refused = select(start, ready)
        if arguments.dry_run:
            print(f"dockerd started {window}")
            for key in selected.values():
                print(f"Would start {key}")
            for key, reason in refused.items():
                print(f"Would leave {key} stopped: {reason}")
            return 0
        if not selected and not refused:
            print(f"No container was stopped by dockerd startup ({window})")
            return 0
        with locked():
            # Compose may have started some while this waited for the lock.
            selected, refused = select(start, ready)
            started, failed = restart(selected) if selected else ([], {})
        failed = {**refused, **failed}
    except Failure as error:
        print(f"Restarting daemon-interrupted containers failed: {error}", file=sys.stderr)
        return 1
    if not started and not failed:
        print(f"No container was stopped by dockerd startup ({window})")
        return 0
    lines = [f"dockerd stopped running containers while starting ({window}); live-restore is off."]
    if started:
        lines.append("Started again: " + ", ".join(sorted(started)))
    for key, problem in sorted(failed.items()):
        lines.append(f"{key}: {problem}")
    message = "\n".join(lines)
    print(message, file=sys.stderr if failed else sys.stdout, flush=True)
    host = socket.gethostname()
    if failed:
        notify(f"Containers left stopped after Docker restart on {host}", message, "high", "warning,whale")
        return 1
    notify(f"Docker restarted interrupted containers on {host}", message, "default", "whale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
