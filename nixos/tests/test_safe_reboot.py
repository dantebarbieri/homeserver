"""Reboot decisions and recovery, with no real systemctl or Docker operations."""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("safe_reboot", ROOT / "nixos/safe-reboot.py")
reboot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reboot)

REBOOT_REQUEST = (
    "busctl", "--system", "--allow-interactive-authorization=no",
    "call", "org.freedesktop.login1", "/org/freedesktop/login1",
    "org.freedesktop.login1.Manager", "RebootWithFlags", "t", "1",
)


def state(active="inactive", sub="dead", job="0", result="success"):
    return dict(LoadState="loaded", ActiveState=active, SubState=sub, Job=job, Result=result)


class ShutdownAccepted(Exception):
    pass


class SafeRebootTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("STATE", "WIKI_BACKUPS", "MD"):
            target = self.root / name
            target.mkdir()
            self.patch(name, target)
        for name in ("COMPOSE_LOCK", "CONTROL_LOCK", "DEPLOYMENT_HOLD"):
            self.patch(name, self.root / name)
        reboot.COMPOSE_LOCK.touch()
        (reboot.MD / "sync_action").write_text("idle\n")
        (reboot.MD / "degraded").write_text("0\n")
        self.states = {}
        self.patch("unit_state", lambda unit: self.states.get(unit, state()))
        self.commands = []
        self.patch("run", self.run_command)
        self.config = {"services": ["backup.service"], "timers": ["backup.timer", "disabled.timer"]}

    def patch(self, name, value):
        patcher = patch.object(reboot, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_command(self, *args, check=True):
        self.commands.append(args)
        if args[:2] == ("docker", "info"):
            stdout = "false\n"
        elif args == ("systemctl", "is-system-running"):
            stdout = "running\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def test_busy_unit_states_and_queued_jobs(self):
        for active, sub, job in (
            ("activating", "start", "0"), ("active", "running", "0"),
            ("deactivating", "stop", "0"), ("reloading", "reload", "0"),
            ("inactive", "dead", "25"),
        ):
            with self.subTest(active=active, job=job):
                self.states["backup.service"] = state(active, sub, job)
                self.assertEqual(len(reboot.blockers(self.config["services"])), 1)
        self.states["backup.service"] = state("active", "exited")
        self.assertEqual(reboot.blockers(self.config["services"]), [])

    def test_failed_or_unknown_job_result_is_not_idle_success(self):
        for value in (state("failed", "failed", result="exit-code"), state(result="timeout"), state(result="")):
            with self.subTest(value=value):
                self.states["backup.service"] = value
                with self.assertRaisesRegex(reboot.RebootError, "inspect its journal"):
                    reboot.blockers(self.config["services"])

    def test_raid_and_operator_hold(self):
        for action in ("check", "repair", "resync", "recover", "reshape", "frozen"):
            with self.subTest(action=action):
                (reboot.MD / "sync_action").write_text(action)
                self.assertEqual(reboot.blockers([]), [f"RAID md0 ({action})"])
        (reboot.MD / "degraded").write_text("1")
        (reboot.MD / "sync_action").write_text("recover")
        self.assertEqual(reboot.blockers([]), ["RAID md0 (recover)"])
        (reboot.MD / "sync_action").write_text("idle")
        with self.assertRaisesRegex(reboot.RebootError, "degraded"):
            reboot.blockers([])
        (reboot.MD / "degraded").write_text("0")
        reboot.DEPLOYMENT_HOLD.touch()
        self.assertIn("operator deployment hold", reboot.blockers([])[0])
        self.assertTrue(reboot.DEPLOYMENT_HOLD.exists())

    def test_unknown_or_missing_raid_state_fails_closed(self):
        (reboot.MD / "sync_action").write_text("unexpected")
        with self.assertRaises(reboot.RebootError):
            reboot.blockers([])
        (reboot.MD / "sync_action").unlink()
        with self.assertRaises(OSError):
            reboot.blockers([])

    def test_real_compose_and_directory_locks(self):
        for path, label in ((reboot.COMPOSE_LOCK, "Compose"), (reboot.WIKI_BACKUPS, "SQL")):
            with self.subTest(path=path):
                fd = os.open(path, os.O_RDONLY)
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    with reboot.maintenance_locks() as reasons:
                        self.assertEqual(len(reasons), 1)
                        self.assertIn(label, reasons[0])
                finally:
                    os.close(fd)
        with reboot.maintenance_locks() as reasons:
            self.assertEqual(reasons, [])
            with reboot.locked(reboot.WIKI_BACKUPS) as acquired:
                self.assertFalse(acquired)
        with reboot.locked(reboot.WIKI_BACKUPS) as acquired:
            self.assertTrue(acquired)

    def test_check_does_not_queue_or_pause_anything(self):
        self.assertEqual(reboot.check(self.config["services"]), 0)
        self.states["backup.service"] = state("activating", "start")
        self.assertEqual(reboot.check(self.config["services"]), 1)
        self.assertFalse((reboot.STATE / "pending").exists())
        self.assertTrue(all(command[0] == "docker" for command in self.commands))
        self.assertIn(("docker", "exec", "mirklurk-backup", "bash",
                       "/opt/mirklurk-backup.sh", "--healthcheck"), self.commands)

    def test_live_restore_or_docker_error_refuses_reboot(self):
        with patch.object(reboot, "run", return_value=subprocess.CompletedProcess([], 0, "true\n", "")):
            with self.assertRaisesRegex(reboot.RebootError, "live-restore"):
                reboot.verify_docker_shutdown()
        with patch.object(reboot, "run", side_effect=reboot.RebootError("daemon unavailable")):
            with self.assertRaisesRegex(reboot.RebootError, "unavailable"):
                reboot.verify_docker_shutdown()

    def test_only_active_and_queued_timers_are_restored(self):
        self.states["backup.timer"] = state("active", "waiting")
        self.states["queued.timer"] = state(job="5")
        (reboot.STATE / "pending").touch()
        reboot.pause_timers(self.config["timers"] + ["queued.timer"])
        self.assertEqual(json.loads((reboot.STATE / "timers.json").read_text()), ["backup.timer", "queued.timer"])
        reboot.cleanup()
        self.assertIn(("systemctl", "stop", "backup.timer", "queued.timer"), self.commands)
        self.assertIn(("systemctl", "--no-block", "start", "backup.timer", "queued.timer"), self.commands)
        self.assertFalse(reboot.STATE.exists())

    def test_partial_timer_stop_failure_keeps_recovery_record(self):
        self.states["backup.timer"] = state("active", "waiting")
        with patch.object(reboot, "run", side_effect=reboot.RebootError("stop failed")):
            with self.assertRaises(reboot.RebootError):
                reboot.pause_timers(self.config["timers"])
        self.assertEqual(json.loads((reboot.STATE / "timers.json").read_text()), ["backup.timer"])
        reboot.cleanup()
        self.assertIn(("systemctl", "--no-block", "start", "backup.timer"), self.commands)

    def test_cleanup_failure_preserves_timer_record_for_retry(self):
        (reboot.STATE / "timers.json").write_text('["backup.timer"]')
        (reboot.STATE / "pending").touch()

        def fail_start(*args, **kwargs):
            if "start" in args:
                raise reboot.RebootError("cannot restore")
            return self.run_command(*args, **kwargs)

        with patch.object(reboot, "run", side_effect=fail_start):
            with self.assertRaisesRegex(reboot.RebootError, "cannot restore"):
                reboot.cleanup()
        self.assertTrue((reboot.STATE / "timers.json").exists())
        reboot.cleanup()
        self.assertFalse(reboot.STATE.exists())

    def test_cleanup_during_shutdown_does_not_rearm_timers(self):
        (reboot.STATE / "pending").touch()
        (reboot.STATE / "timers.json").write_text('["backup.timer"]')
        with patch.object(reboot, "run", return_value=subprocess.CompletedProcess([], 1, "stopping\n", "")) as run:
            reboot.cleanup()
            run.assert_called_once_with("systemctl", "is-system-running", check=False)
        self.assertTrue((reboot.STATE / "pending").exists())

    def test_worker_waits_then_rechecks_and_holds_locks_through_shutdown(self):
        self.states["backup.timer"] = state("active", "waiting")
        self.states["backup.service"] = state("activating", "start")

        def sleep(seconds):
            if seconds == reboot.POLL_SECONDS:
                self.states["backup.service"] = state()
                return
            self.assertEqual(seconds, 3600)
            for path in (reboot.COMPOSE_LOCK, reboot.WIKI_BACKUPS):
                with reboot.locked(path) as acquired:
                    self.assertFalse(acquired)
            raise ShutdownAccepted

        with patch.object(reboot.time, "sleep", side_effect=sleep):
            with self.assertRaises(ShutdownAccepted):
                reboot.worker(self.config)
        self.assertTrue((reboot.STATE / "pending").exists())
        self.assertTrue((reboot.STATE / "committed").exists())
        self.assertEqual(self.commands.count(REBOOT_REQUEST), 1)
        self.assertNotIn(("systemctl", "reboot"), self.commands)
        self.assertNotIn(("systemctl", "stop", "backup.service"), self.commands)

    def test_final_recheck_prevents_racing_job(self):
        with patch.object(reboot, "blockers", side_effect=[[], ["new job"]]), \
             patch.object(reboot.time, "sleep", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                reboot.worker(self.config)
        self.assertFalse(any(command[0] == "busctl" or "reboot" in command for command in self.commands))
        reboot.cleanup()

    def test_busy_lock_is_retried_without_reboot(self):
        with reboot.locked(reboot.COMPOSE_LOCK), \
             patch.object(reboot.time, "sleep", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                reboot.worker(self.config)
        self.assertFalse(any(command[0] == "busctl" or "reboot" in command for command in self.commands))

    def test_rejected_reboot_restores_timers_and_releases_locks(self):
        self.states["backup.timer"] = state("active", "waiting")

        def reject(*args, **kwargs):
            result = self.run_command(*args, **kwargs)
            if args[0] == "busctl":
                raise reboot.RebootError("shutdown inhibited")
            return result

        with patch.object(reboot, "run", side_effect=reject):
            with self.assertRaisesRegex(reboot.RebootError, "inhibited"):
                reboot.worker(self.config)
        self.assertFalse((reboot.STATE / "committed").exists())
        self.assertEqual(self.commands.count(REBOOT_REQUEST), 1)
        self.assertFalse(any(command[0] == "systemctl" and "reboot" in command for command in self.commands))
        with reboot.locked(reboot.WIKI_BACKUPS) as acquired:
            self.assertTrue(acquired)
        reboot.cleanup()
        self.assertIn(("systemctl", "--no-block", "start", "backup.timer"), self.commands)

    def test_logind_errors_never_fall_back_to_an_unchecked_reboot(self):
        for error in (
            reboot.RebootError("Unknown method RebootWithFlags"),
            reboot.RebootError("Failed to connect to bus"),
            subprocess.TimeoutExpired("busctl", 60),
            FileNotFoundError("busctl"),
        ):
            with self.subTest(error=error):
                reboot.STATE.mkdir(exist_ok=True)
                self.commands.clear()
                self.states["backup.timer"] = state("active", "waiting")

                def fail_logind(*args, **kwargs):
                    result = self.run_command(*args, **kwargs)
                    if args[0] == "busctl":
                        raise error
                    return result

                with patch.object(reboot, "run", side_effect=fail_logind):
                    with self.assertRaises(type(error)):
                        reboot.worker(self.config)
                self.assertEqual(self.commands.count(REBOOT_REQUEST), 1)
                self.assertFalse(any(command[0] == "systemctl" and "reboot" in command for command in self.commands))
                self.assertFalse((reboot.STATE / "committed").exists())
                reboot.cleanup()
                self.assertIn(("systemctl", "--no-block", "start", "backup.timer"), self.commands)
                self.assertFalse(reboot.STATE.exists())

    def test_request_is_idempotent_and_cancel_is_not_shutdown_cancel(self):
        reboot.request()
        self.assertIn(("systemctl", "--no-block", "start", reboot.UNIT), self.commands)
        self.states[reboot.UNIT] = state("active", "running")
        reboot.request()
        self.assertEqual(self.commands.count(("systemctl", "--no-block", "start", reboot.UNIT)), 1)
        reboot.cancel()
        self.assertIn(("systemctl", "stop", reboot.UNIT), self.commands)
        reboot.STATE.mkdir()
        (reboot.STATE / "committed").touch()
        with self.assertRaisesRegex(reboot.RebootError, "too late"):
            reboot.cancel()

    def test_cli_rejects_non_root_and_direct_internal_modes(self):
        with patch.object(reboot.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(reboot.RebootError, "sudo"):
                reboot.main(["unused.json"])
        with patch.object(reboot.os, "geteuid", return_value=0), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(reboot.RebootError, "systemd"):
                reboot.main(["unused.json", "--worker"])


class UnitStateTests(unittest.TestCase):
    def test_missing_masked_and_incomplete_units_fail_closed(self):
        for output in ("", "LoadState=not-found\nActiveState=inactive\nSubState=dead\nJob=\n",
                       "LoadState=masked\nActiveState=inactive\nSubState=dead\nJob=0\n"):
            with self.subTest(output=output), \
                 patch.object(reboot, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                with self.assertRaises(reboot.RebootError):
                    reboot.unit_state("backup.service")

    def test_systemctl_errors_are_not_interpreted_as_inactive(self):
        result = subprocess.CompletedProcess([], 1, "", "Failed to connect to bus")
        with patch.object(reboot.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(reboot.RebootError, "Failed to connect"):
                reboot.run("systemctl", "show", "backup.service")


if __name__ == "__main__":
    unittest.main()
