"""Evaluate NixOS settings and exercise maintenance scripts without a server."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HealthCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Evaluate the flake exactly as the server does. git+file only sees
        # tracked files, so `git add` new modules before running this.
        result = subprocess.run(
            [
                "nix-instantiate", "--eval", "--strict", "--json",
                "--extra-experimental-features", "nix-command flakes",
                "--argstr", "flakeRef", f"git+file://{ROOT.as_posix()}?dir=nixos",
                "-E",
                """
                { flakeRef }:
                let
                  system = (builtins.getFlake flakeRef).nixosConfigurations.homeserver;
                  c = system.config;
                  hm = c.home-manager.users.danteb;
                in {
                  failedAssertions = map (a: a.message)
                    (builtins.filter (a: !a.assertion) c.assertions);
                  upgradeScript = c.systemd.services.nixos-upgrade.script;
                  allowReboot = c.system.autoUpgrade.allowReboot;
                  systemGit = c.programs.git.config;
                  home = {
                    inherit (hm.programs.zsh) dotDir profileExtra initContent;
                    gitUser = hm.programs.git.settings.user;
                    gitSigning = { inherit (hm.programs.git.signing) key format; };
                    files = builtins.attrNames hm.home.file;
                  };
                  primary = c.systemd.network.networks."40-enp66s0f1".networkConfig;
                  mailSyncService = builtins.hasAttr "vdirsyncer-sync" c.systemd.services;
                  mailSyncTimer = builtins.hasAttr "vdirsyncer-sync" c.systemd.timers;
                  packages = map system.pkgs.lib.getName c.environment.systemPackages;
                  shellInit = c.programs.zsh.interactiveShellInit;
                  socketConsumerUnit = {
                    inherit (c.systemd.services.docker-socket-consumers)
                      wantedBy after requires partOf serviceConfig unitConfig;
                  };
                  interruptedContainersUnit = {
                    inherit (c.systemd.services.docker-interrupted-containers)
                      wantedBy after requires partOf serviceConfig unitConfig script;
                    path = map system.pkgs.lib.getName
                      c.systemd.services.docker-interrupted-containers.path;
                  };
                  updateScript = c.systemd.services.docker-compose-update.script;
                  updateFailure = c.systemd.services.docker-compose-update.unitConfig.OnFailure;
                  autoUpdateUnit = {
                    inherit (c.systemd.services.mirklurk-auto-update)
                      after requires unitConfig script;
                    serviceType = c.systemd.services.mirklurk-auto-update.serviceConfig.Type;
                  };
                  autoUpdateTimer = {
                    inherit (c.systemd.timers.mirklurk-auto-update) wantedBy timerConfig unitConfig;
                  };
                  tmpfiles = c.systemd.tmpfiles.rules;
                  scrubFailure = c.systemd.services.mdadm-scrub.unitConfig.OnFailure;
                  upgradeFailure = c.systemd.services.nixos-upgrade.unitConfig.OnFailure;
                  scrubRestart = c.systemd.services.mdadm-scrub.restartIfChanged;
                  scrubScript = c.systemd.services.mdadm-scrub.script;
                  runnerUnit = c.systemd.services.forgejo-runner-worldforge.serviceConfig;
                  runnerMigrate = {
                    inherit (c.systemd.services.forgejo-runner-worldforge-migrate)
                      requiredBy before unitConfig;
                  };
                  nixIndex = {
                    package = system.pkgs.lib.getName c.programs.nix-index.package;
                    inherit (c.programs.nix-index) enable;
                    commandNotFound = c.programs.command-not-found.enable;
                    weeklyService = builtins.hasAttr "nix-index-update" c.systemd.services;
                    weeklyTimer = builtins.hasAttr "nix-index-update" c.systemd.timers;
                  };
                  rebootReminder = {
                    inherit (c.systemd.services.reboot-reminder) script;
                    failure = c.systemd.services.reboot-reminder.unitConfig.OnFailure;
                    type = c.systemd.services.reboot-reminder.serviceConfig.Type;
                    path = map system.pkgs.lib.getName c.systemd.services.reboot-reminder.path;
                    timer = {
                      inherit (c.systemd.timers.reboot-reminder) wantedBy timerConfig;
                    };
                  };
                  safeReboot = {
                    inherit (c.systemd.services.safe-reboot)
                      before wantedBy restartIfChanged serviceConfig unitConfig;
                    guarded = system.pkgs.lib.genAttrs [
                      "postgres-backup" "rclone-offsite-daily" "rclone-offsite-weekly"
                      "docker-compose-update" "docker-socket-consumers" "nixos-upgrade"
                      "mdadm-scrub" "mirklurk-snapshot" "mirklurk-auto-update"
                      "mirklurk-backup-check" "mirklurk-sitemap"
                    ] (name: {
                      inherit (c.systemd.services.${name}) unitConfig restartIfChanged;
                    });
                    docker = c.virtualisation.docker.daemon.settings;
                    dockerStopTimeout = c.systemd.services.docker.serviceConfig.TimeoutStopSec;
                    backupScripts = map (name: c.systemd.services.${name}.script)
                      [ "postgres-backup" "rclone-offsite-daily" "rclone-offsite-weekly" ];
                  };
                  ntfy = {
                    notify = (builtins.head (builtins.filter
                      (p: (p.name or "") == "ntfy-notify")
                      c.environment.systemPackages)).text;
                    flush = c.systemd.services.ntfy-spool-flush.script;
                  };
                  plexAlbumCheck = {
                    inherit (c.systemd.services.plex-album-check) script after wants;
                    failure = c.systemd.services.plex-album-check.unitConfig.OnFailure;
                    inherit (c.systemd.services.plex-album-check.serviceConfig)
                      Type StateDirectory;
                    path = map system.pkgs.lib.getName c.systemd.services.plex-album-check.path;
                    timer = {
                      inherit (c.systemd.timers.plex-album-check) wantedBy timerConfig;
                    };
                  };
                }
                """,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.config = json.loads(result.stdout)
        # programs.git.config merges into a list of INI attrsets.
        cls.systemGit = {}
        for ini in cls.config["systemGit"]:
            for section, values in ini.items():
                cls.systemGit.setdefault(section, {}).update(values)

    def test_nixos_settings(self):
        self.assertEqual(self.config["failedAssertions"], [])
        self.assertIn("nixos-rebuild boot ", self.config["upgradeScript"])
        self.assertNotIn("nixos-rebuild switch ", self.config["upgradeScript"])
        self.assertFalse(self.config["allowReboot"])
        self.assertEqual(self.config["primary"]["Bond"], "bond0")
        self.assertTrue(self.config["primary"]["PrimarySlave"])
        self.assertFalse(self.config["scrubRestart"])
        for key in ("scrubFailure", "updateFailure", "upgradeFailure"):
            self.assertEqual(self.config[key], "ntfy-failure@%n.service")

    def test_upgrade_builds_the_locked_flake(self):
        # Tokenize like bash: an unquoted `&` in the URL would background
        # nixos-rebuild and silently skip the upgrade.
        lexer = shlex.shlex(self.config["upgradeScript"], posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        args = list(lexer)
        self.assertNotIn("&", args)
        # ref=main: only committed content is built or copied into the store.
        self.assertEqual(
            args[args.index("--flake") + 1],
            "git+file:///srv/homeserver?dir=nixos&ref=main#homeserver",
        )
        self.assertIn("--no-update-lock-file", args)
        self.assertNotIn("--upgrade", args)
        # root evaluates the danteb-owned checkout; libgit2 refuses it otherwise.
        self.assertEqual(self.systemGit["safe"]["directory"], "/srv/homeserver")

    def test_home_manager_owns_personal_shell_and_git(self):
        home = self.config["home"]
        self.assertNotIn("user", self.systemGit)
        self.assertEqual(home["gitUser"]["name"], "dantebarbieri")
        self.assertEqual(home["gitSigning"], {"key": "~/.ssh/id_ed25519.pub", "format": "ssh"})
        self.assertEqual(home["dotDir"], "/home/danteb")
        self.assertIn(".zimrc", home["files"])
        # Secrets stay in untracked local files that the managed dotfiles source.
        self.assertIn("~/.zprofile.local", home["profileExtra"])
        self.assertIn("~/.zshrc.local", home["initContent"])
        self.assertIn("zimfw.zsh init", home["initContent"])

    def test_mail_calendar_retired(self):
        self.assertFalse(self.config["mailSyncService"])
        self.assertFalse(self.config["mailSyncTimer"])
        for package in ("aerc", "khard", "khal", "vdirsyncer", "w3m"):
            self.assertNotIn(package, self.config["packages"])
        self.assertNotIn("khal list", self.config["shellInit"])

    def test_nix_locate_uses_the_prebuilt_database(self):
        nix_index = self.config["nixIndex"]
        # Only the database-wrapped package works without a local index, and
        # nothing builds a local index any more (the weekly job had started failing).
        self.assertEqual(nix_index["package"], "nix-index-with-full-db")
        self.assertTrue(nix_index["enable"])
        self.assertFalse(nix_index["commandNotFound"])
        self.assertFalse(nix_index["weeklyService"])
        self.assertFalse(nix_index["weeklyTimer"])

    def test_reboot_reminder_unit_and_timer(self):
        reminder = self.config["rebootReminder"]
        self.assertEqual(reminder["type"], "oneshot")
        self.assertEqual(reminder["failure"], "ntfy-failure@%n.service")
        self.assertIn("reboot-needed", self.config["packages"])
        for tool in ("coreutils", "gawk", "curl", "reboot-needed"):
            self.assertIn(tool, reminder["path"])
        self.assertEqual(reminder["timer"]["timerConfig"]["OnCalendar"], "*-*-* 10:00:00")
        self.assertIn("timers.target", reminder["timer"]["wantedBy"])
        self.assertIn("stale_days=7\n", reminder["script"])
        self.assertIn("message=$(reboot-needed)", reminder["script"])

    def test_safe_reboot_unit_and_guards(self):
        reboot = self.config["safeReboot"]
        self.assertIn("safe-reboot", self.config["packages"])
        self.assertEqual(reboot["wantedBy"], [])
        self.assertIn("docker.service", reboot["before"])
        self.assertFalse(reboot["restartIfChanged"])
        self.assertEqual(reboot["unitConfig"]["OnFailure"], "ntfy-failure@%n.service")
        service = reboot["serviceConfig"]
        self.assertEqual(service["Type"], "exec")
        self.assertTrue(service["ExecStart"].endswith("/bin/safe-reboot --worker"))
        self.assertTrue(service["ExecStopPost"].endswith("/bin/safe-reboot --cleanup"))
        self.assertEqual(service["RuntimeDirectory"], "safe-reboot")
        self.assertTrue(service["RuntimeDirectoryPreserve"])
        for name, job in reboot["guarded"].items():
            with self.subTest(name=name):
                self.assertFalse(job["restartIfChanged"])
                self.assertIn("!/run/safe-reboot/pending", job["unitConfig"]["ConditionPathExists"])
        for name in ("rclone-offsite-daily", "docker-compose-update", "nixos-upgrade",
                     "mirklurk-snapshot", "mirklurk-auto-update", "mirklurk-backup-check"):
            self.assertIn("!/var/lib/mirklurk-upload-deployment/hold",
                          reboot["guarded"][name]["unitConfig"]["ConditionPathExists"])
        self.assertFalse(reboot["docker"]["live-restore"])
        self.assertEqual(reboot["docker"]["default-stop-timeout"], 180)
        self.assertGreater(reboot["docker"]["shutdown-timeout"], 180)
        self.assertEqual(reboot["dockerStopTimeout"], "240s")

    def test_backup_target_failures_fail_the_unit(self):
        for script in self.config["safeReboot"]["backupScripts"]:
            # Run the actual final notification/exit block without touching data.
            condition = 'if [ -n "$FAILED" ]; then'
            self.assertIn(condition, script)
            tail = condition + script.rsplit(condition, 1)[1]
            # An undeliverable alert must not hide the failure from systemd.
            for failed, notify, expected in (("", 0, 0), ("failed-target", 0, 1),
                                             ("failed-target", 7, 1)):
                with self.subTest(failed=failed, notify=notify, script=script[:60]):
                    result = subprocess.run(
                        ["bash", "-eu", "-c",
                         'ntfy-notify() { return "$NOTIFY_STATUS"; }\n' + tail],
                        env={**os.environ, "FAILED": failed, "SUCCEEDED": "ok",
                             "NOTIFY_STATUS": str(notify)},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_database_dumps_retry_and_name_stopped_containers(self):
        script = self.config["safeReboot"]["backupScripts"][0]
        start = script.index("dump() {")
        dump = script[start:script.index("\n}\n", start) + 3]
        harness = (
            'sleep() { :; }\n'
            'docker() { [ "$1 $2" = "inspect --format" ] && echo "$STATE"; }\n'
            'produce() {\n'
            '  n=$(( $(cat "$COUNTER") + 1 )); echo "$n" > "$COUNTER"\n'
            '  case "$MODE" in\n'
            '    fail-once) [ "$n" -gt 1 ] || return 1; seq 1 1000 ;;\n'
            '    fail) return 1 ;;\n'
            '    empty) ;;\n'
            '  esac\n'
            '}\n'
        )
        # (container state, dump behaviour, RESULT, dump attempts, file kept)
        cases = [
            ("exited", "fail-once", "not running: exited", 0, False),
            ("running", "fail-once", "ok", 2, True),
            ("running", "empty", "empty", 3, False),
            ("running", "fail", "dump failed", 3, False),
        ]
        for state, mode, expected, attempts, kept in cases:
            with self.subTest(state=state, mode=mode), tempfile.TemporaryDirectory() as tmp:
                counter, out = Path(tmp) / "count", Path(tmp) / "db.sql.gz"
                counter.write_text("0")
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c",
                     harness + dump + 'dump db "$OUT" produce\nprintf %s "$RESULT"'],
                    env={**os.environ, "STATE": state, "MODE": mode,
                         "COUNTER": str(counter), "OUT": str(out)},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(int(counter.read_text()), attempts)
                self.assertEqual(out.exists(), kept)

    def _fake_curl(self, tmp):
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$CURL_LOG"\n'
                        'exit "$CURL_STATUS"\n')
        curl.chmod(0o755)
        return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "CURL_LOG": str(Path(tmp) / "curl.log")}

    def test_undeliverable_alerts_are_queued(self):
        notify = self.config["ntfy"]["notify"]
        # Use the fake curl below, never a real one from the store.
        self.assertRegex(notify, r"(?m)^PATH=/nix/store/.*:\$PATH$")
        notify = re.sub(r"(?m)^PATH=.*\n", "", notify, count=1)
        self.assertIn("SPOOL=/var/lib/ntfy-spool\n", notify)
        # (curl exit status, spool exists, expected exit status, queued)
        for curl_status, spool_exists, expected, queued in (
            (0, True, 0, 0), (7, True, 0, 1), (22, False, 22, 0),
        ):
            with self.subTest(curl=curl_status, spool=spool_exists), \
                    tempfile.TemporaryDirectory() as tmp:
                spool = Path(tmp) / "spool"
                if spool_exists:
                    spool.mkdir()
                script = Path(tmp) / "ntfy-notify"
                script.write_text(notify.replace("SPOOL=/var/lib/ntfy-spool\n",
                                                 f"SPOOL={spool}\n"))
                result = subprocess.run(
                    ["bash", str(script), "Title", "line one\nline two", "high", "warning"],
                    env={**self._fake_curl(tmp), "CURL_STATUS": str(curl_status)},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                entries = sorted(spool.glob("*.alert")) if spool_exists else []
                self.assertEqual(len(entries), queued)
                if queued:
                    entry = entries[0]
                    self.assertEqual((entry / "title").read_text(), "Title")
                    self.assertEqual((entry / "message").read_text(), "line one\nline two")
                    self.assertEqual((entry / "priority").read_text(), "high")
                    self.assertEqual((entry / "tags").read_text(), "warning")
                    self.assertEqual(list(spool.glob(".new.*")), [])

    def test_queued_alerts_are_delivered_in_order_once_ntfy_is_back(self):
        flush = self.config["ntfy"]["flush"]
        for curl_status in (0, 7):
            with self.subTest(curl=curl_status), tempfile.TemporaryDirectory() as tmp:
                spool = Path(tmp) / "spool"
                for name, title in (("20261110T011100000000000-2", "first"),
                                    ("20261110T011200000000000-1", "second")):
                    entry = spool / f"{name}.alert"
                    entry.mkdir(parents=True)
                    for field, value in (("title", title), ("message", f"{title} body"),
                                         ("priority", "high"), ("tags", "warning"),
                                         ("queued", "2026-11-10 01:11:00 UTC")):
                        (entry / field).write_text(value)
                stale = spool / ".new.abandoned"
                stale.mkdir()
                old = time.time() - 2 * 3600
                os.utime(stale, (old, old))
                env = {**self._fake_curl(tmp), "CURL_STATUS": str(curl_status)}
                result = subprocess.run(
                    ["bash", "-e", "-c", flush.replace("/var/lib/ntfy-spool", str(spool))],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(stale.exists())
                calls = Path(env["CURL_LOG"]).read_text()
                if curl_status == 0:
                    self.assertEqual(list(spool.iterdir()), [])
                    self.assertLess(calls.index("Title: first (delayed)"),
                                    calls.index("Title: second (delayed)"))
                    self.assertIn("Queued at 2026-11-10 01:11:00 UTC", calls)
                else:
                    # Stop at the first failure and keep everything queued.
                    self.assertEqual(len(list(spool.glob("*.alert"))), 2)
                    self.assertEqual(calls.count("Title: "), 1)

    def test_reboot_reminder_decisions(self):
        script = self.config["rebootReminder"]["script"]
        for original, fake in (
            ("uptime_file=/proc/uptime", 'uptime_file="$TEST_ROOT/uptime"'),
            ("md_sync=/sys/block/md0/md/sync_action", 'md_sync="$TEST_ROOT/sync_action"'),
        ):
            self.assertIn(original + "\n", script)
            script = script.replace(original + "\n", fake + "\n")
        harness = (
            'reboot-needed() { printf "%s\\n" "$REBOOT_MESSAGE"; return "$REBOOT_STATUS"; }\n'
            'curl() { printf "CURL:%s\\n" "$*"; return "$CURL_STATUS"; }\n'
        )

        # (label, uptime days, reboot-needed exit status,
        #  RAID action or None for no md device, curl exit status,
        #  sent, expected exit status, text expected in the output)
        cases = [
            ("recently rebooted", 6.9, 1, "idle", 0, False, 0, "Up 6 days"),
            ("nothing staged", 30, 0, "idle", 0, False, 0, "No reboot needed"),
            ("updates waiting", 30, 1, "idle", 0, True, 0, "sudo safe-reboot"),
            ("exactly at the threshold", 7, 1, "idle", 0, True, 0, "Up 7 days"),
            ("no md device", 30, 1, None, 0, True, 0, "Reboot needed"),
            ("scrub running", 30, 1, "check", 0, False, 0,
             "RAID md0 is running 'check'; not reminding until it is idle"),
            ("rebuild running", 30, 1, "recover", 0, False, 0,
             "RAID md0 is running 'recover'"),
            ("unknown state", 30, 2, "idle", 0, False, 2, "Cannot determine"),
            ("checker failed", 30, 127, "idle", 0, False, 127, "Cannot determine"),
            ("ntfy unreachable", 30, 1, "idle", 22, True, 22, "CURL:"),
        ]
        for label, days, reboot_status, action, curl_status, sent, expected, text in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "uptime").write_text(f"{int(days * 86400)}.25 0.00\n")
                if action is not None:
                    (root / "sync_action").write_text(action + "\n")
                message = (
                    "No reboot needed for installed updates." if reboot_status == 0
                    else "Reboot needed to activate installed changes.\nRun sudo safe-reboot when ready."
                )
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", harness + script],
                    env={**os.environ, "TEST_ROOT": tmp, "CURL_STATUS": str(curl_status),
                         "REBOOT_STATUS": str(reboot_status), "REBOOT_MESSAGE": message},
                    capture_output=True,
                    text=True,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, expected, output)
                self.assertIn(text, output)
                self.assertEqual("CURL:" in result.stdout, sent, output)
                if sent:
                    self.assertIn("Title: Reboot needed on homeserver", result.stdout)
                    self.assertIn("Tags: arrows_counterclockwise,computer", result.stdout)
                    self.assertIn("https://ntfy.danteb.com/homeserver-alerts", result.stdout)
                    self.assertIn("--fail-with-body --show-error --silent --max-time 30", result.stdout)

    def test_plex_album_check_unit_and_timer(self):
        check = self.config["plexAlbumCheck"]
        self.assertEqual(check["Type"], "oneshot")
        self.assertEqual(check["StateDirectory"], "plex-album-check")
        self.assertEqual(check["failure"], "ntfy-failure@%n.service")
        self.assertIn("docker.service", check["after"])
        self.assertIn("network-online.target", check["wants"])
        for tool in ("coreutils", "curl", "docker", "gawk", "gnugrep", "jq"):
            self.assertIn(tool, check["path"])
        self.assertEqual(check["timer"]["timerConfig"]["OnCalendar"], "*-*-* 06:30:00")
        self.assertIn("timers.target", check["timer"]["wantedBy"])
        self.assertIn("remind_days=7\n", check["script"])

    def test_plex_album_check_decisions(self):
        script = self.config["plexAlbumCheck"]["script"]
        state_dir = "state_dir=/var/lib/plex-album-check\n"
        self.assertIn(state_dir, script)
        script = script.replace(state_dir, 'state_dir="$TEST_ROOT/state"\n')
        # The fake docker records its arguments and the SQL it was fed, then
        # replays a canned Plex answer (nothing at all, like an empty result).
        harness = (
            'docker() { printf "%s\\n" "$*" > "$TEST_ROOT/docker.args"; '
            'cat > "$TEST_ROOT/docker.stdin"; '
            '[ ! -f "$TEST_ROOT/plex.json" ] || cat "$TEST_ROOT/plex.json"; '
            'return "$DOCKER_STATUS"; }\n'
            'curl() { printf "CURL:%s\\n" "$*"; return "$CURL_STATUS"; }\n'
        )

        def album(album_id, artist, name, folders):
            # One track per entry of folders; repeat a folder for more tracks.
            return [
                {
                    "album_id": album_id,
                    "artist": artist,
                    "album": name,
                    "file": f"/data/media/music/{artist}/{folder}/{number:02d} - Song.flac",
                }
                for number, folder in enumerate(folders, 1)
            ]

        clean = album(1, "AJR", "The Maybe Man", ["The Maybe Man (2023)"] * 3)
        discs = album(2, "Hans Zimmer", "Inception", [
            "Inception (2010)/CD1", "Inception (2010)/CD 2",
            "Inception (2010)/Disc 3", "Inception (2010)/disk 4",
        ])
        stray = album(3, "Daft Punk", "Alive", [
            "Alive 2007 (2007)/CD1", "Alive 2007 (2007)/CD2", "Alive 1997 (1997)",
        ])
        ajr = album(4, "AJR", "Neotheater", [
            "Neotheater (2019)", "Neotheater (2019)",
            "Neotheater (Deluxe) (2019)", "Neotheater (Deluxe) (2019)",
            "Neotheater (Live) (2020)",
        ])
        ghibli = album(5, "Studio Ghibli", "Collection", ["Spirited Away (2001)", "Totoro (1988)"])
        many = [
            track
            for n in range(15)
            for track in album(100 + n, f"Artist {n:02d}", f"Album {n:02d}", [f"A{n}", f"B{n}"])
        ]
        header = "Plex merged several album folders into one album"
        repair = 'Repair: docker/docs/MUSIC.md, section "Fixing merged Plex albums".'
        ajr_line = "- AJR - Neotheater (3 folders, 5 tracks)"
        ghibli_line = "- Studio Ghibli - Collection (2 folders, 2 tracks)"

        def run(rows, known, alerted, docker_status, curl_status):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "state").mkdir()
                if rows is not None:
                    (root / "plex.json").write_text(json.dumps(rows))
                for name, content in (("known", known), ("alerted", alerted)):
                    if content is not None:
                        (root / "state" / name).write_text(content)
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", harness + script],
                    env={
                        **os.environ,
                        "TEST_ROOT": tmp,
                        "DOCKER_STATUS": str(docker_status),
                        "CURL_STATUS": str(curl_status),
                    },
                    capture_output=True,
                    text=True,
                )

                def read(name):
                    path = root / name
                    return path.read_text() if path.exists() else None

                return result, {
                    name: read(name)
                    for name in ("state/known", "state/alerted", "docker.args", "docker.stdin")
                }

        # Each case: library rows (None = Plex prints nothing), the known file,
        # how many days ago the last alert was (or raw text), docker and curl
        # exit statuses, then the expected exit status, whether ntfy was
        # called, text that must / must not be in the output, and the state
        # left behind: the known names (None = no file) and the alert time.
        cases = [
            dict(label="clean library, multi-disc albums are one album",
                 rows=clean + discs, rc=0, text=["No Plex album spans more than one folder"],
                 known_after=None, alerted_after=None),
            dict(label="disc folders do not hide a real merge",
                 rows=clean + discs + stray, sent=True,
                 text=[header, "- Daft Punk - Alive (2 folders, 3 tracks)", repair],
                 absent=["Hans Zimmer"], known_after=["Daft Punk - Alive"], alerted_after="fresh"),
            dict(label="new merge",
                 rows=clean + ajr, sent=True,
                 text=[header, ajr_line, repair, "Title: Merged Plex albums on homeserver",
                       "Tags: warning,musical_note", "https://ntfy.danteb.com/homeserver-alerts",
                       "--fail-with-body --show-error --silent --max-time 30"],
                 known_after=["AJR - Neotheater"], alerted_after="fresh"),
            dict(label="already reported",
                 rows=clean + ajr, known="AJR - Neotheater\n", alerted=1,
                 text=["Already reported: 1 merged album(s)"],
                 known_after=["AJR - Neotheater"], alerted_after="same"),
            dict(label="weekly reminder",
                 rows=clean + ajr, known="AJR - Neotheater\n", alerted=8, sent=True,
                 text=["Still merged in Plex", ajr_line, repair], absent=[header],
                 known_after=["AJR - Neotheater"], alerted_after="fresh"),
            dict(label="unreadable alert time reminds",
                 rows=clean + ajr, known="AJR - Neotheater\n", alerted="not a number\n", sent=True,
                 text=["Still merged in Plex", ajr_line],
                 known_after=["AJR - Neotheater"], alerted_after="fresh"),
            dict(label="a second merge lists only the new one",
                 rows=clean + ajr + ghibli, known="AJR - Neotheater\n", alerted=1, sent=True,
                 text=[header, ghibli_line], absent=[ajr_line],
                 known_after=["AJR - Neotheater", "Studio Ghibli - Collection"],
                 alerted_after="fresh"),
            dict(label="a repaired merge is forgotten",
                 rows=clean + ajr, known="AJR - Neotheater\nStudio Ghibli - Collection\n", alerted=1,
                 text=["Already reported: 1 merged album(s)"],
                 known_after=["AJR - Neotheater"], alerted_after="same"),
            dict(label="repairing everything clears the state",
                 rows=clean, known="AJR - Neotheater\n", alerted=1,
                 text=["No Plex album spans more than one folder"],
                 known_after=None, alerted_after=None),
            dict(label="ntfy unreachable keeps the merge unreported",
                 rows=clean + ajr, curl=22, sent=True, rc=22, text=["CURL:"],
                 known_after=None, alerted_after=None),
            dict(label="docker failure",
                 rows=clean + ajr, docker=3, rc=3, known_after=None, alerted_after=None),
            dict(label="empty result is an error, not a clean library",
                 rows=None, rc=1, text=["Plex returned no music tracks"],
                 known_after=None, alerted_after=None),
            dict(label="long lists are capped",
                 rows=many, sent=True,
                 text=["- Artist 00 - Album 00 (2 folders, 2 tracks)",
                       "- Artist 11 - Album 11 (2 folders, 2 tracks)", "...and 3 more"],
                 absent=["Artist 12"], known_after=[f"Artist {n:02d} - Album {n:02d}" for n in range(15)],
                 alerted_after="fresh"),
        ]
        for case in cases:
            with self.subTest(case["label"]):
                alerted = case.get("alerted")
                if isinstance(alerted, int):
                    alerted = f"{int(time.time() - alerted * 86400)}\n"
                result, files = run(
                    case["rows"], case.get("known"), alerted,
                    case.get("docker", 0), case.get("curl", 0),
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, case.get("rc", 0), output)
                self.assertEqual("CURL:" in result.stdout, case.get("sent", False), output)
                for text in case.get("text", []):
                    self.assertIn(text, output)
                for text in case.get("absent", []):
                    self.assertNotIn(text, output)

                known = files["state/known"]
                if case["known_after"] is None:
                    self.assertIsNone(known)
                else:
                    self.assertEqual(sorted(known.splitlines()), sorted(case["known_after"]))
                if case["alerted_after"] is None:
                    self.assertIsNone(files["state/alerted"])
                elif case["alerted_after"] == "same":
                    self.assertEqual(files["state/alerted"], alerted)
                else:
                    self.assertLess(abs(int(files["state/alerted"]) - time.time()), 300)

                # Whatever the outcome, Plex was only ever read.
                args, sql = files["docker.args"], files["docker.stdin"]
                self.assertIn("exec -i plex ", args)
                self.assertIn("-bail -readonly -json", args)
                self.assertTrue(sql.lstrip().startswith("SELECT"), sql)
                self.assertEqual(sql.count(";"), 1, sql)
                self.assertIsNone(
                    re.search(r"\b(insert|update|delete|drop|alter|attach|pragma|create|replace)\b", sql, re.I),
                    sql,
                )

    def test_forgejo_runner_static_user_and_migration(self):
        unit = self.config["runnerUnit"]
        self.assertFalse(unit["DynamicUser"])
        self.assertEqual((unit["User"], unit["Group"]), ("forgejo-runner", "forgejo-runner"))
        self.assertEqual(
            unit["LoadCredential"],
            ["server__connections__default__token_url:/var/lib/forgejo-runner-worldforge.token"],
        )
        migrate = self.config["runnerMigrate"]
        for key in ("requiredBy", "before"):
            self.assertEqual(migrate[key], ["forgejo-runner-worldforge.service"])
        self.assertEqual(
            migrate["unitConfig"]["ConditionPathExists"],
            "/var/lib/gitea-runner/worldforge/.runner",
        )

    def test_socket_reconciliation_follows_daemon_lifecycle(self):
        unit = self.config["socketConsumerUnit"]
        for key in ("wantedBy", "after", "requires", "partOf"):
            self.assertIn("docker.service", unit[key])
        self.assertEqual(unit["serviceConfig"]["Type"], "oneshot")
        self.assertTrue(unit["serviceConfig"]["RemainAfterExit"])
        self.assertEqual(
            unit["serviceConfig"]["WorkingDirectory"], "/srv/homeserver/docker"
        )
        self.assertEqual(unit["unitConfig"]["OnFailure"], "ntfy-failure@%n.service")

    def test_interrupted_containers_are_restarted_after_every_daemon_start(self):
        unit = self.config["interruptedContainersUnit"]
        # PartOf re-runs it when dockerd restarts, including after a crash.
        for key in ("wantedBy", "after", "requires", "partOf"):
            self.assertIn("docker.service", unit[key])
        self.assertEqual(unit["serviceConfig"]["Type"], "oneshot")
        self.assertTrue(unit["serviceConfig"]["RemainAfterExit"])
        self.assertEqual(unit["unitConfig"]["OnFailure"], "ntfy-failure@%n.service")
        self.assertIn("restart-daemon-interrupted-containers.py", unit["script"])
        # A pending safe reboot must not silently skip recovery; it only waits.
        self.assertNotIn("ConditionPathExists", unit["unitConfig"])
        for tool in ("docker", "systemd", "ntfy-notify"):
            self.assertIn(tool, unit["path"])

    def test_wiki_auto_update_follows_the_updater_with_alerts_and_the_shared_hold(self):
        unit, timer = self.config["autoUpdateUnit"], self.config["autoUpdateTimer"]
        self.assertIn("docker-compose-update.service", unit["after"])
        self.assertIn("docker.service", unit["requires"])
        self.assertEqual(unit["unitConfig"]["OnFailure"], "ntfy-failure@%n.service")
        self.assertIn("!/var/lib/mirklurk-upload-deployment/hold", unit["unitConfig"]["ConditionPathExists"])
        self.assertEqual(timer["unitConfig"]["ConditionPathExists"], "!/var/lib/mirklurk-upload-deployment/hold")
        self.assertEqual(unit["serviceType"], "oneshot")
        self.assertIn("/srv/homeserver/docker/scripts/mirklurk-release.py auto-update", unit["script"])
        self.assertNotIn("--dry-run", unit["script"])
        self.assertEqual(timer["timerConfig"]["OnCalendar"], "*-*-* 04:15:00")
        self.assertTrue(timer["timerConfig"]["Persistent"])
        self.assertIn("timers.target", timer["wantedBy"])
        self.assertIn("d /var/lib/mirklurk-auto-update 2775 root docker - -", self.config["tmpfiles"])
        self.assertIn("d /var/lib/mirklurk-upload-deployment 0755 root root - -", self.config["tmpfiles"])

    def test_update_sequence_and_build_isolation(self):
        harness = """
        flock() { echo LOCK; return "$LOCK_STATUS"; }
        git() {
          case "$*" in
            *' rev-parse HEAD') echo before-sha; return 0 ;;
            *' diff --name-only -z before-sha HEAD')
              printf '%s\\0' new/sub/file.txt existing.txt deleted.txt
              return 0 ;;
          esac
          printf 'GIT:%s\\n' "$*"; return "$GIT_STATUS"
        }
        chown() { printf 'CHOWN:%s\\n' "$*"; return "$CHOWN_STATUS"; }
        cd() { echo CD; }
        sleep() { printf 'SLEEP:%s\\n' "$1"; }
        # Tdarr update guard (docker/scripts/tdarr-update-guard.sh) and the
        # Prowlarr definition refresh (docker/scripts/setup-prowlarr-definitions.sh).
        bash() {
          printf 'GUARD:%s\\n' "$*"
          case "$1" in
            scripts/setup-prowlarr-definitions.sh) return "$DEFINITIONS_STATUS" ;;
          esac
          return 0
        }
        pull_attempts=0
        docker() {
          if [ "$1" = ps ]; then return 0; fi
          if [ "$*" = 'compose config --services' ]; then
            printf 'DOCKER:%s\\n' "$*" >&2
            printf '%s\\n' convertx homepage radarr
            return 0
          fi
          printf 'DOCKER:%s\\n' "$*"
          case "$*" in
            'compose --parallel 4 pull --ignore-buildable')
              pull_attempts=$((pull_attempts + 1))
              if [ "$pull_attempts" -le "$PULL_FAILURES" ]; then return 1; fi ;;
            'compose pull --ignore-buildable '*)
              case " $FAILING_PULLS " in *" ${@: -1} "*) return 1 ;; esac ;;
            'compose build --pull')
              return "$BUILD_STATUS" ;;
            'compose build --pull '*)
              case " $FAILING_BUILDS " in *" ${@: -1} "*) return 1 ;; esac ;;
            'compose up -d --remove-orphans'*)
              return "$DEPLOY_STATUS" ;;
          esac
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
            {"PULL_FAILURES": "3", "FAILING_PULLS": "radarr"},
            {"PULL_FAILURES": "3", "FAILING_PULLS": "radarr",
             "BUILD_STATUS": "1", "FAILING_BUILDS": "convertx"},
            {"BUILD_STATUS": "1"},
            {"BUILD_STATUS": "1", "FAILING_BUILDS": "convertx"},
            {"BUILD_STATUS": "1", "FAILING_BUILDS": "convertx", "DEPLOY_STATUS": "1"},
            {"DEPLOY_STATUS": "1"},
            {"DEFINITIONS_STATUS": "1"},
            {"DEFINITIONS_STATUS": "1", "BUILD_STATUS": "1", "FAILING_BUILDS": "convertx"},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                statuses = dict.fromkeys(
                    ("LOCK_STATUS", "GIT_STATUS", "CHOWN_STATUS",
                     "PULL_FAILURES", "BUILD_STATUS", "DEPLOY_STATUS",
                     "DEFINITIONS_STATUS"), "0",
                )
                statuses["FAILING_BUILDS"] = ""
                statuses["FAILING_PULLS"] = ""
                statuses.update(overrides)
                with tempfile.TemporaryDirectory() as snapshots:
                    # Work tree as the pull left it: one new nested file, one
                    # updated file; deleted.txt was removed by the pull.
                    tree = Path(snapshots) / "tree"
                    (tree / "new" / "sub").mkdir(parents=True)
                    (tree / "new" / "sub" / "file.txt").write_text("x")
                    (tree / "existing.txt").write_text("x")
                    result = subprocess.run(
                        ["bash", "-euo", "pipefail", "-c", harness + script],
                        cwd=tree,
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
                deploy_failed = statuses["DEPLOY_STATUS"] != "0"
                definitions_failed = statuses["DEFINITIONS_STATUS"] != "0"
                build_held = statuses["FAILING_BUILDS"].split()
                pull_held = statuses["FAILING_PULLS"].split() if exhausted else []
                held = pull_held + build_held
                failed = failed_before_pull or deploy_failed or bool(held) or definitions_failed
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
                    self.assertNotIn("CHOWN:-h", result.stdout)
                    self.assertNotIn("CD", result.stdout)
                    self.assertNotIn("DOCKER:compose --parallel 4 pull", result.stdout)
                else:
                    # Only what the pull changed (and its directories) is handed
                    # back, after the pull and before any Compose work.
                    chowns = [
                        line for line in result.stdout.splitlines() if line.startswith("CHOWN:")
                    ]
                    self.assertEqual(chowns, [
                        "CHOWN:-R danteb:docker .git",
                        "CHOWN:-h danteb:docker new/sub/file.txt",
                        "CHOWN:-h danteb:docker new/sub",
                        "CHOWN:-h danteb:docker new",
                        "CHOWN:-h danteb:docker existing.txt",
                    ])
                    self.assertLess(
                        result.stdout.index("pull --ff-only"), result.stdout.index("CHOWN:")
                    )
                    self.assertLess(result.stdout.index("CHOWN:-h"), result.stdout.index("CD"))
                    attempts = min(3, int(statuses["PULL_FAILURES"]) + 1)
                    self.assertEqual(
                        result.stdout.count("DOCKER:compose --parallel 4 pull"), attempts
                    )
                    sleeps = [
                        line for line in result.stdout.splitlines() if line.startswith("SLEEP:")
                    ]
                    self.assertEqual(sleeps, ["SLEEP:60", "SLEEP:120"][:attempts - 1])
                if failed_before_pull:
                    self.assertNotIn("DOCKER:compose build", result.stdout)
                    self.assertNotIn("DOCKER:compose up", result.stdout)
                    continue
                lines = result.stdout.splitlines()
                # An exhausted combined pull falls back to one service at a
                # time; a failing service is held back, never the whole stack.
                for svc in ("convertx", "homepage", "radarr"):
                    single_pull = f"DOCKER:compose pull --ignore-buildable {svc}"
                    self.assertEqual(single_pull in lines, exhausted)
                if exhausted:
                    self.assertLess(
                        result.stdout.rindex("DOCKER:compose --parallel 4 pull"),
                        result.stdout.index("DOCKER:compose pull --ignore-buildable"),
                    )
                    self.assertLess(
                        result.stdout.index("DOCKER:compose pull --ignore-buildable"),
                        result.stdout.index("DOCKER:compose build --pull"),
                    )
                if statuses["BUILD_STATUS"] != "0":
                    for svc in ("convertx", "homepage", "radarr"):
                        self.assertIn(f"DOCKER:compose build --pull {svc}", lines)
                else:
                    self.assertNotIn("DOCKER:compose build --pull convertx", lines)
                if held:
                    # Everything except the held services deploys; they keep their old containers.
                    deployed = [s for s in ("convertx", "homepage", "radarr") if s not in held]
                    self.assertIn(
                        "DOCKER:compose up -d --remove-orphans " + " ".join(deployed), lines
                    )
                    self.assertNotIn("DOCKER:compose up -d --remove-orphans", lines)
                    for svc in held:
                        self.assertIn(svc, result.stderr)
                    if pull_held and not deploy_failed:
                        self.assertIn("failed to pull: " + " ".join(pull_held), result.stderr)
                    if build_held and not deploy_failed:
                        self.assertIn("failed to build: " + " ".join(build_held), result.stderr)
                else:
                    self.assertIn("DOCKER:compose up -d --remove-orphans", lines)
                self.assertLess(
                    lines.index("GUARD:scripts/tdarr-update-guard.sh prepare"),
                    next(i for i, line in enumerate(lines) if line.startswith("DOCKER:compose up")),
                )
                self.assertIn("GUARD:scripts/tdarr-update-guard.sh release", lines)
                if deploy_failed:
                    self.assertNotIn("DOCKER:image prune -f", lines)
                    self.assertNotIn("GUARD:scripts/setup-prowlarr-definitions.sh", lines)
                else:
                    # Definitions are refreshed after the deploy; a failure is
                    # reported but never stops the rest of the update.
                    self.assertLess(
                        lines.index("GUARD:scripts/tdarr-update-guard.sh release"),
                        lines.index("GUARD:scripts/setup-prowlarr-definitions.sh"),
                    )
                    self.assertEqual(
                        "Prowlarr's custom definitions need review" in result.stderr,
                        definitions_failed,
                    )
                    self.assertIn("DOCKER:compose up -d --force-recreate homepage", lines)
                    self.assertIn("DOCKER:image prune -f", lines)
                    self.assertIn("DOCKER:network prune -f", lines)

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
