"""Nix-managed, opt-in reboot coordinator. Internal modes run only via systemd."""

import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


UNIT = "safe-reboot.service"
STATE = Path("/run/safe-reboot")
CONTROL_LOCK = Path("/run/lock/homeserver-safe-reboot.lock")
COMPOSE_LOCK = Path("/run/lock/homeserver-compose.lock")
WIKI_BACKUPS = Path("/srv/docker/data/mirklurk/backups")
DEPLOYMENT_HOLD = Path("/var/lib/mirklurk-upload-deployment/hold")
MD = Path("/sys/block/md0/md")
POLL_SECONDS = 15


class RebootError(Exception):
    pass


def run(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise RebootError(
            f"{' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def unit_state(unit):
    result = run(
        "systemctl", "show", unit,
        "--property=LoadState,ActiveState,SubState,Job,Result",
    )
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    for key in ("LoadState", "ActiveState", "SubState", "Job"):
        if key not in state:
            raise RebootError(f"Cannot determine {key} for {unit}")
    if state["LoadState"] != "loaded":
        raise RebootError(f"{unit} is {state['LoadState']}; refusing an unverified reboot")
    return state


def busy(state):
    return (
        state["Job"] not in ("", "0")
        or state["ActiveState"] not in ("inactive", "failed", "active")
        or (state["ActiveState"] == "active" and state["SubState"] != "exited")
    )


def blockers(services):
    reasons = []
    for unit in services:
        state = unit_state(unit)
        if busy(state):
            reasons.append(f"{unit} ({state['ActiveState']}/{state['SubState']})")
        elif state["ActiveState"] == "failed" or state.get("Result") != "success":
            raise RebootError(f"{unit} failed; inspect its journal and repair/reset-failed before rebooting")

    action = (MD / "sync_action").read_text().strip()
    degraded = (MD / "degraded").read_text().strip()
    if not degraded.isdecimal():
        raise RebootError(f"Invalid RAID md0 degraded={degraded!r}")
    if action not in ("idle", "check", "repair", "resync", "recover", "reshape", "frozen"):
        raise RebootError(f"Unrecognized RAID md0 sync_action={action!r}")
    if action != "idle":
        reasons.append(f"RAID md0 ({action})")
    elif degraded != "0":
        raise RebootError(f"RAID md0 degraded={degraded!r}; investigate before rebooting")
    if os.path.lexists(DEPLOYMENT_HOLD):
        reasons.append(f"operator deployment hold: {DEPLOYMENT_HOLD}")
    return reasons


@contextmanager
def locked(path, *, create=False, blocking=False):
    flags = os.O_RDONLY | os.O_CLOEXEC | (os.O_CREAT if create else 0)
    fd = os.open(path, flags, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


@contextmanager
def maintenance_locks():
    with ExitStack() as stack:
        reasons = []
        for path, create, label in (
            (COMPOSE_LOCK, False, "Compose deployment/update lock"),
            (WIKI_BACKUPS, False, "MirkLurk SQL backup"),
        ):
            if not stack.enter_context(locked(path, create=create)):
                reasons.append(label)
        yield reasons


def verify_docker_shutdown():
    live_restore = run("docker", "info", "--format", "{{json .LiveRestoreEnabled}}").stdout.strip()
    if live_restore != "false":
        raise RebootError("Docker live-restore is not disabled; activate the safe-reboot NixOS configuration first")
    run("docker", "exec", "mirklurk-backup", "bash", "/opt/mirklurk-backup.sh", "--healthcheck")


def check(services):
    reasons = blockers(services)
    verify_docker_shutdown()
    with maintenance_locks() as lock_reasons:
        reasons += lock_reasons
    print("Waiting for: " + "; ".join(reasons) if reasons else "No reboot blockers detected.", flush=True)
    return 1 if reasons else 0


def pause_timers(timers):
    # Persist the original active set before any stop, including partial failures.
    active = []
    for timer in timers:
        state = unit_state(timer)
        if state["ActiveState"] == "active" or busy(state):
            active.append(timer)
    (STATE / "timers.json").write_text(json.dumps(active))
    if active:
        run("systemctl", "stop", *active)


def cleanup():
    if not STATE.exists():
        return
    # Never re-arm timers in the shutdown transaction (including an unrelated reboot).
    shutting_down = run("systemctl", "is-system-running", check=False)
    if shutting_down.stdout.strip() == "stopping":
        return
    if shutting_down.stdout.strip() not in ("running", "degraded", "starting", "maintenance"):
        raise RebootError("Cannot determine whether shutdown is underway; timers remain paused")
    if (STATE / "committed").exists():
        return
    (STATE / "pending").unlink(missing_ok=True)
    saved = STATE / "timers.json"
    if saved.exists():
        timers = json.loads(saved.read_text())
        if timers:
            run("systemctl", "--no-block", "start", *timers)
        saved.unlink()
    STATE.rmdir()
    print("Safe reboot canceled/failed; previously active timers restored.", flush=True)


def worker(config):
    if (STATE / "timers.json").exists():
        raise RebootError("Previous timer recovery is unfinished; run sudo safe-reboot --cancel first")
    (STATE / "pending").touch()
    pause_timers(config["timers"])
    previous = None
    while True:
        reasons = blockers(config["services"])
        if not reasons:
            with maintenance_locks() as lock_reasons:
                reasons += lock_reasons
                if not reasons:
                    # Serialize cancellation with the irreversible reboot request.
                    with locked(CONTROL_LOCK, create=True, blocking=True):
                        reasons = blockers(config["services"])
                        if not reasons:
                            verify_docker_shutdown()
                            print("Backups and maintenance idle; requesting orderly reboot.", flush=True)
                            committed = STATE / "committed"
                            committed.touch()
                            try:
                                run("systemctl", "--check-inhibitors=yes", "reboot")
                            except (RebootError, subprocess.TimeoutExpired, OSError):
                                committed.unlink()
                                raise
                    if not reasons:
                        # Docker stops first; keep both locks until systemd stops us.
                        while True:
                            time.sleep(3600)
        message = "Waiting for: " + "; ".join(reasons)
        if message != previous:
            print(message, flush=True)
            previous = message
        time.sleep(POLL_SECONDS)


def request():
    with locked(CONTROL_LOCK, create=True, blocking=True):
        state = unit_state(UNIT)
        if busy(state):
            print("A safe reboot is already queued. Use sudo safe-reboot --status.", flush=True)
            return
        run("systemctl", "--no-block", "start", UNIT)
        print("Safe reboot queued; SSH may disconnect safely. Use --status or --cancel.", flush=True)


def cancel():
    with locked(CONTROL_LOCK, create=True, blocking=True):
        if (STATE / "committed").exists():
            raise RebootError("Shutdown has already been requested; it is too late to cancel")
        run("systemctl", "stop", UNIT)
        cleanup()
        print("Safe reboot canceled.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="safe-reboot", description="Queue a backup-aware reboot; no arguments queues it."
    )
    parser.add_argument("config", help=argparse.SUPPRESS)
    modes = parser.add_mutually_exclusive_group()
    for mode, help_text in (
        ("check", "show current blockers without queuing a reboot"),
        ("status", "show the queued reboot's status and recent journal"),
        ("cancel", "cancel before shutdown begins and restore paused timers"),
        ("worker", argparse.SUPPRESS),
        ("cleanup", argparse.SUPPRESS),
    ):
        modes.add_argument(f"--{mode}", action="store_true", help=help_text)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise RebootError("Run this command with sudo")
    if (args.worker or args.cleanup) and not os.environ.get("INVOCATION_ID"):
        raise RebootError("Internal modes may only be run by systemd")
    config = json.loads(Path(args.config).read_text())
    if args.check:
        return check(config["services"])
    if args.status:
        result = run("systemctl", "--no-pager", "--full", "status", UNIT, check=False)
        print(result.stdout + result.stderr, end="")
        return result.returncode
    if args.cancel:
        cancel()
    elif args.cleanup:
        cleanup()
    elif args.worker:
        worker(config)
    else:
        request()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RebootError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"safe-reboot: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
