"""Evaluate NixOS settings and exercise maintenance scripts without a server."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HealthCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [
                "nix-instantiate", "--eval", "--strict", "--json", "-E",
                """
                let
                  system = import <nixpkgs/nixos> {
                    configuration = ./nixos/configuration.nix;
                  };
                  c = system.config;
                in {
                  failedAssertions = map (a: a.message)
                    (builtins.filter (a: !a.assertion) c.assertions);
                  upgradeScript = c.systemd.services.nixos-upgrade.script;
                  allowReboot = c.system.autoUpgrade.allowReboot;
                  primary = c.systemd.network.networks."40-enp66s0f1".networkConfig;
                  mailSyncService = builtins.hasAttr "vdirsyncer-sync" c.systemd.services;
                  mailSyncTimer = builtins.hasAttr "vdirsyncer-sync" c.systemd.timers;
                  packages = map system.pkgs.lib.getName c.environment.systemPackages;
                  shellInit = c.programs.zsh.interactiveShellInit;
                  socketConsumerService = builtins.hasAttr "docker-socket-consumers" c.systemd.services;
                  updateScript = c.systemd.services.docker-compose-update.script;
                  updateFailure = c.systemd.services.docker-compose-update.unitConfig.OnFailure;
                  scrubFailure = c.systemd.services.mdadm-scrub.unitConfig.OnFailure;
                  scrubRestart = c.systemd.services.mdadm-scrub.restartIfChanged;
                  scrubScript = c.systemd.services.mdadm-scrub.script;
                }
                """,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.config = json.loads(result.stdout)

    def test_nixos_settings(self):
        self.assertEqual(self.config["failedAssertions"], [])
        self.assertIn("nixos-rebuild boot ", self.config["upgradeScript"])
        self.assertNotIn("nixos-rebuild switch ", self.config["upgradeScript"])
        self.assertFalse(self.config["allowReboot"])
        self.assertEqual(self.config["primary"]["Bond"], "bond0")
        self.assertTrue(self.config["primary"]["PrimarySlave"])
        self.assertFalse(self.config["scrubRestart"])
        for key in ("scrubFailure", "updateFailure"):
            self.assertEqual(self.config[key], "ntfy-failure@%n.service")

    def test_mail_calendar_retired_and_container_hook_deferred(self):
        self.assertFalse(self.config["mailSyncService"])
        self.assertFalse(self.config["mailSyncTimer"])
        self.assertFalse(self.config["socketConsumerService"])
        for package in ("aerc", "khard", "khal", "vdirsyncer", "w3m"):
            self.assertNotIn(package, self.config["packages"])
        self.assertNotIn("khal list", self.config["shellInit"])

    def test_update_preserves_fail_fast_sequence(self):
        harness = """
        flock() { echo LOCK; return "$LOCK_STATUS"; }
        git() { printf 'GIT:%s\\n' "$*"; return "$GIT_STATUS"; }
        chown() { echo CHOWN; return "$CHOWN_STATUS"; }
        cd() { echo CD; }
        sleep() { printf 'SLEEP:%s\\n' "$1"; }
        pull_attempts=0
        docker() {
          if [ "$1" = ps ]; then return 0; fi
          printf 'DOCKER:%s\\n' "$*"
          if [ "$*" = 'compose --parallel 4 pull --ignore-buildable' ]; then
            pull_attempts=$((pull_attempts + 1))
            if [ "$pull_attempts" -le "$PULL_FAILURES" ]; then return 1; fi
          elif [ "$*" = 'compose build --pull' ]; then
            return "$BUILD_STATUS"
          elif [ "$*" = 'compose up -d --remove-orphans' ]; then
            return "$DEPLOY_STATUS"
          fi
          return 0
        }
        """
        script = self.config["updateScript"]
        self.assertIn("SNAPSHOT_DIR=/srv/docker/image-snapshots", script)
        script = script.replace(
            "SNAPSHOT_DIR=/srv/docker/image-snapshots",
            'SNAPSHOT_DIR="$TEST_SNAPSHOT_DIR"',
        )
        self.assertIn("exec 9>/run/lock/homeserver-compose.lock\nflock 9", script)
        script = script.replace(
            "exec 9>/run/lock/homeserver-compose.lock",
            'exec 9>"$TEST_LOCK_PATH"',
        )
        cases = [
            {}, {"LOCK_STATUS": "1"}, {"GIT_STATUS": "1"}, {"CHOWN_STATUS": "1"},
            {"PULL_FAILURES": "1"}, {"PULL_FAILURES": "2"}, {"PULL_FAILURES": "3"},
            {"BUILD_STATUS": "1"}, {"DEPLOY_STATUS": "1"},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                statuses = dict.fromkeys(
                    ("LOCK_STATUS", "GIT_STATUS", "CHOWN_STATUS",
                     "PULL_FAILURES", "BUILD_STATUS", "DEPLOY_STATUS"), "0",
                )
                statuses.update(overrides)
                with tempfile.TemporaryDirectory() as snapshots:
                    result = subprocess.run(
                        ["bash", "-euo", "pipefail", "-c", harness + script],
                        env={
                            **os.environ,
                            "TEST_SNAPSHOT_DIR": snapshots,
                            "TEST_LOCK_PATH": str(Path(snapshots) / "compose.lock"),
                            **statuses,
                        },
                        capture_output=True,
                        text=True,
                    )
                failed_before_pull = any(
                    statuses[key] != "0" for key in ("LOCK_STATUS", "GIT_STATUS", "CHOWN_STATUS")
                )
                exhausted = int(statuses["PULL_FAILURES"]) >= 3
                failed = (
                    failed_before_pull or exhausted
                    or statuses["BUILD_STATUS"] != "0" or statuses["DEPLOY_STATUS"] != "0"
                )
                self.assertEqual(result.returncode, int(failed), result.stderr)
                if statuses["LOCK_STATUS"] != "0":
                    self.assertNotIn("GIT:", result.stdout)
                    continue
                self.assertIn(
                    "-c maintenance.autoDetach=false -c gc.autoDetach=false pull --ff-only",
                    result.stdout,
                )
                self.assertLess(result.stdout.index("LOCK"), result.stdout.index("GIT:"))
                if statuses["GIT_STATUS"] != "0":
                    self.assertNotIn("CHOWN", result.stdout)
                if failed_before_pull:
                    self.assertNotIn("CD", result.stdout)
                    self.assertNotIn("DOCKER:compose --parallel 4 pull", result.stdout)
                else:
                    attempts = min(3, int(statuses["PULL_FAILURES"]) + 1)
                    self.assertEqual(
                        result.stdout.count("DOCKER:compose --parallel 4 pull"), attempts
                    )
                    sleeps = [
                        line for line in result.stdout.splitlines() if line.startswith("SLEEP:")
                    ]
                    self.assertEqual(sleeps, ["SLEEP:60", "SLEEP:120"][:attempts - 1])
                if failed_before_pull or exhausted:
                    self.assertNotIn("DOCKER:compose build", result.stdout)
                if failed_before_pull or exhausted or statuses["BUILD_STATUS"] != "0":
                    self.assertNotIn("DOCKER:compose up", result.stdout)
                if failed:
                    self.assertNotIn("DOCKER:image prune", result.stdout)
                else:
                    self.assertIn("DOCKER:compose build --pull", result.stdout)
                    self.assertIn("DOCKER:compose up -d --remove-orphans", result.stdout)
                    self.assertIn("DOCKER:compose up -d --force-recreate homepage", result.stdout)
                    self.assertIn("DOCKER:network prune -f", result.stdout)

    def test_scrub_monitor_state_and_error_paths(self):
        harness = """
        cat() {
          if [[ "$1" == "$TEST_MD_DIR/sync_action" ]]; then
            local index
            local -a actions
            read -r index < "$TEST_MD_DIR/action_index"
            IFS=, read -r -a actions <<< "$ACTIONS"
            if (( index >= ${#actions[@]} )); then index=$((${#actions[@]} - 1)); fi
            printf '%s\\n' "${actions[$index]}"
            printf '%s\\n' "$((index + 1))" > "$TEST_MD_DIR/action_index"
          else
            command cat "$@"
          fi
        }
        sleep() { :; }
        curl() { printf 'CURL:%s\\n' "$*"; return "$CURL_STATUS"; }
        """
        script = self.config["scrubScript"].replace(
            "SYNC=/sys/block/$MD/md/sync_action", 'SYNC="$TEST_MD_DIR/sync_action"'
        ).replace(
            "MISMATCH=/sys/block/$MD/md/mismatch_cnt", 'MISMATCH="$TEST_MD_DIR/mismatch_cnt"'
        )
        cases = [
            ("idle,check,check,idle", "0", 0, 0, True, "RAID Scrub Clean"),
            ("check,check,check,idle", "0", 0, 0, False, "Monitoring existing"),
            ("recover", "0", 0, 1, False, "Cannot start"),
            ("idle", "0", 0, 1, True, "did not start"),
            ("idle,recover", "0", 0, 1, True, "Unexpected RAID action"),
            ("check,check,recover", "0", 0, 1, False, "replaced by unexpected"),
            ("check,check,idle", "12", 0, 1, False, "RAID Scrub Found Mismatches"),
            ("check,check,idle", "invalid", 0, 1, False, "Invalid mismatch count"),
            ("check,check,idle", None, 0, 1, False, "mismatch_cnt"),
            ("check,check,idle", "0", 22, 22, False, "CURL:"),
        ]
        for actions, mismatch, curl_status, expected, started, message in cases:
            with self.subTest(actions=actions, mismatch=mismatch, curl=curl_status):
                with tempfile.TemporaryDirectory() as md_dir:
                    md = Path(md_dir)
                    (md / "action_index").write_text("0\n")
                    (md / "sync_action").write_text("untouched\n")
                    if mismatch is not None:
                        (md / "mismatch_cnt").write_text(mismatch + "\n")
                    result = subprocess.run(
                        ["bash", "-euo", "pipefail", "-c", harness + script],
                        env={
                            **os.environ, "TEST_MD_DIR": md_dir, "ACTIONS": actions,
                            "CURL_STATUS": str(curl_status),
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        (md / "sync_action").read_text(), "check\n" if started else "untouched\n"
                    )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn(message, result.stdout + result.stderr)
                if "CURL:" in result.stdout:
                    self.assertIn("--fail-with-body --show-error --silent --max-time 30", result.stdout)
                if expected and curl_status == 0:
                    self.assertNotIn("RAID Scrub Clean", result.stdout)


if __name__ == "__main__":
    unittest.main()
