"""Evaluate NixOS settings and exercise maintenance scripts without a server."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
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
        for tool in ("coreutils", "gawk", "curl"):
            self.assertIn(tool, reminder["path"])
        self.assertEqual(reminder["timer"]["timerConfig"]["OnCalendar"], "*-*-* 10:00:00")
        self.assertIn("timers.target", reminder["timer"]["wantedBy"])
        self.assertIn("stale_days=7\n", reminder["script"])

    def test_reboot_reminder_decisions(self):
        script = self.config["rebootReminder"]["script"]
        for original, fake in (
            ("booted=/run/booted-system", 'booted="$TEST_ROOT/booted"'),
            ("current=/run/current-system", 'current="$TEST_ROOT/current"'),
            ("staged=/nix/var/nix/profiles/system", 'staged="$TEST_ROOT/staged"'),
            ("uptime_file=/proc/uptime", 'uptime_file="$TEST_ROOT/uptime"'),
            ("md_sync=/sys/block/md0/md/sync_action", 'md_sync="$TEST_ROOT/sync_action"'),
        ):
            self.assertIn(original + "\n", script)
            script = script.replace(original + "\n", fake + "\n")
        harness = 'curl() { printf "CURL:%s\\n" "$*"; return "$CURL_STATUS"; }\n'

        def make_system(root, name, kernel, initrd, modules, version):
            # The links a NixOS system closure carries; the booted one is
            # /run/booted-system, the next-boot one the system profile.
            closure = root / "store" / name
            closure.mkdir(parents=True)
            (root / "store" / modules / "lib" / "modules" / version).mkdir(parents=True, exist_ok=True)
            (closure / "kernel").symlink_to(f"/store/{kernel}/bzImage")
            (closure / "initrd").symlink_to(f"/store/{initrd}/initrd")
            (closure / "kernel-modules").symlink_to(root / "store" / modules)
            return closure

        # (label, uptime days, what was staged, running the staged closure,
        #  RAID action or None for no md device, curl exit status,
        #  sent, expected exit status, text expected in the output)
        cases = [
            ("recently rebooted", 6.9, "kernel", True, "idle", 0, False, 0, "Up 6 days"),
            ("nothing staged", 30, "same", True, "idle", 0, False, 0, "nothing to do"),
            ("new kernel", 30, "kernel", True, "idle", 0, True, 0,
             "Kernel update staged: running 6.18.54, next boot 6.18.59."),
            ("new kernel and userland", 30, "kernel", False, "idle", 0, True, 0,
             "running 6.18.54, next boot 6.18.59"),
            ("driver only", 30, "modules", True, "idle", 0, True, 0,
             "Kernel modules or initrd changed on 6.18.54 (e.g. an NVIDIA driver update)."),
            ("userland only", 30, "same", False, "idle", 0, True, 0,
             "OS updates are staged but not running yet."),
            ("exactly at the threshold", 7, "same", False, "idle", 0, True, 0, "Up 7 days"),
            ("no md device", 30, "kernel", True, None, 0, True, 0, "Kernel update staged"),
            ("scrub running", 30, "kernel", True, "check", 0, False, 0,
             "RAID md0 is running 'check'; not reminding until it is idle"),
            ("rebuild running", 30, "same", False, "recover", 0, False, 0,
             "RAID md0 is running 'recover'"),
            ("ntfy unreachable", 30, "kernel", True, "idle", 22, True, 22, "CURL:"),
        ]
        for label, days, staged, running_staged, action, curl_status, sent, expected, text in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                booted = make_system(root, "sys-a", "k-54", "i-54", "m-54", "6.18.54")
                kernel, initrd, modules, version = {
                    "same": ("k-54", "i-54", "m-54", "6.18.54"),
                    "kernel": ("k-59", "i-59", "m-59", "6.18.59"),
                    "modules": ("k-54", "i-54", "m-54-nvidia", "6.18.54"),
                }[staged]
                next_boot = make_system(root, "sys-b", kernel, initrd, modules, version)
                (root / "booted").symlink_to(booted)
                (root / "staged").symlink_to(next_boot)
                (root / "current").symlink_to(next_boot if running_staged else booted)
                (root / "uptime").write_text(f"{int(days * 86400)}.25 0.00\n")
                if action is not None:
                    (root / "sync_action").write_text(action + "\n")
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", harness + script],
                    env={**os.environ, "TEST_ROOT": tmp, "CURL_STATUS": str(curl_status)},
                    capture_output=True,
                    text=True,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, expected, output)
                self.assertIn(text, output)
                self.assertEqual("CURL:" in result.stdout, sent, output)
                if sent:
                    self.assertIn("Title: Reboot pending on homeserver", result.stdout)
                    self.assertIn("Tags: arrows_counterclockwise,computer", result.stdout)
                    self.assertIn("https://ntfy.danteb.com/homeserver-alerts", result.stdout)
                    self.assertIn("--fail-with-body --show-error --silent --max-time 30", result.stdout)

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

    def test_wiki_auto_update_follows_the_updater_with_alerts_and_the_shared_hold(self):
        unit, timer = self.config["autoUpdateUnit"], self.config["autoUpdateTimer"]
        self.assertIn("docker-compose-update.service", unit["after"])
        self.assertIn("docker.service", unit["requires"])
        self.assertEqual(unit["unitConfig"]["OnFailure"], "ntfy-failure@%n.service")
        for gated in (unit["unitConfig"], timer["unitConfig"]):
            self.assertEqual(gated["ConditionPathExists"], "!/var/lib/mirklurk-upload-deployment/hold")
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
        # Tdarr update guard (docker/scripts/tdarr-update-guard.sh).
        bash() { printf 'GUARD:%s\\n' "$*"; return 0; }
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
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                statuses = dict.fromkeys(
                    ("LOCK_STATUS", "GIT_STATUS", "CHOWN_STATUS",
                     "PULL_FAILURES", "BUILD_STATUS", "DEPLOY_STATUS"), "0",
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
                build_held = statuses["FAILING_BUILDS"].split()
                pull_held = statuses["FAILING_PULLS"].split() if exhausted else []
                held = pull_held + build_held
                failed = failed_before_pull or deploy_failed or bool(held)
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
                else:
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
