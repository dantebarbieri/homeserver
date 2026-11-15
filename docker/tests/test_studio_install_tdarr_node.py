import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
MACOS = ROOT / "macos"
INSTALLER = MACOS / "install/install-tdarr-node.sh"
BASH = shutil.which("bash")
LABEL = "com.danteb.studio-tdarr"
MODULES = ("hevc-offload-v1.cjs", "hevc-safe-v1.cjs", "dv5-sidecar.cjs")
INPUTS = (
    "mount-studio-share.c",
    "studio-tdarr-launcher.c",
    "start-tdarr-session.sh",
    "start-tdarr.sh",
    f"{LABEL}.plist",
)

# The installer is a macOS root script. These stand in for the macOS tools it
# calls so its own logic runs unchanged. Flags are files in the state directory
# because the worker side runs under `env -i`, which drops the environment.
STUBS = {
    "uname": "echo Darwin",
    "id": r"""
case "$*" in
    -u) [[ -e @STATE@/not-root ]] && echo 501 || echo 0 ;;
    "-u _studio") [[ -e @STATE@/studio-root ]] && echo 0 || echo 499 ;;
    -un) [[ -e @STATE@/wrong-user ]] && echo root || echo _studio ;;
    *) exec @REAL_ID@ "$@" ;;
esac
""",
    # The worker runs under `env -i`, so give its PATH the stubs and the host's own tools.
    # Only `bash -c` runs the worker's install script; that call is logged separately.
    "sudo": r"""
[[ -e @STATE@/sudo-fails ]] && exit 1
while [[ $1 == -n || $1 == -H ]]; do shift; done
if [[ $1 == -u ]]; then
    echo "sudo-as $2" >>@STATE@/log
    for arg in "$@"; do
        [[ $arg == -c ]] && echo "sudo-script-as $2" >>@STATE@/log
    done
    shift 2
fi
args=()
for arg in "$@"; do
    [[ $arg == PATH=* ]] && arg="PATH=@BIN@:${arg#PATH=}:$PATH"
    args+=("$arg")
done
exec "${args[@]}"
""",
    "sleep": "true",
    "launchctl": r"""
echo "launchctl $*" >>@STATE@/log
case $1 in
    print) [[ -e @STATE@/loaded ]] ;;
    bootout) [[ -e @STATE@/bootout-sticks ]] || rm -f @STATE@/loaded ;;
    bootstrap)
        count=$(cat @STATE@/bootstraps 2>/dev/null || echo 0)
        echo $((count + 1)) >@STATE@/bootstraps
        if (( count < $(cat @STATE@/bootstrap-fails 2>/dev/null || echo 0) )); then
            echo "Bootstrap failed: 5: Input/output error" >&2
            exit 5
        fi
        [[ -e @STATE@/bootstrap-no-load ]] || touch @STATE@/loaded ;;
esac
""",
    # The workers-gone-after flag holds how many calls still see the processes.
    "pgrep": r"""
echo "pgrep $*" >>@STATE@/log
calls=$(cat @STATE@/pgrep-calls 2>/dev/null || echo 0)
echo $((calls + 1)) >@STATE@/pgrep-calls
if [[ -e @STATE@/workers-gone-after ]] && (( calls >= $(cat @STATE@/workers-gone-after) )); then
    exit 1
fi
[[ -s @STATE@/workers ]] && cat @STATE@/workers
""",
    # The clang-fails flag holds a substring of the output path to fail on; empty fails every build.
    "clang": r"""
echo "clang $*" >>@STATE@/log
while (( $# )); do
    [[ $1 == -o ]] && { out=$2; shift; }
    shift
done
if [[ -e @STATE@/clang-fails && $out == *"$(cat @STATE@/clang-fails)"* ]]; then
    echo "clang: error: build failed" >&2
    exit 1
fi
echo "built by clang" >"$out"
chmod 755 "$out"
""",
    "codesign": r"""
echo "codesign $*" >>@STATE@/log
[[ $1 == -dvvv ]] && printf 'Identifier=com.danteb.studio-tdarr-launcher\nCDHash=0123456789abcdef\n' >&2
true
""",
    "plutil": r"""
[[ -e @STATE@/plutil-fails ]] && { echo "$2: Malformed" >&2; exit 1; }
echo "$2: OK"
""",
    "sqlite3": "[[ -e @STATE@/no-fda ]] || echo 2",
    "install": r"""
echo "install $*" >>@STATE@/log
mode= dir=0 args=()
while (( $# )); do
    case $1 in
        -o | -g) shift 2 ;;
        -m) mode=$2; shift 2 ;;
        -d) dir=1; shift ;;
        *) args+=("$1"); shift ;;
    esac
done
if (( dir )); then
    for path in "${args[@]}"; do
        mkdir -p "$path"
        [[ -z $mode ]] || chmod "$mode" "$path"
    done
else
    cp "${args[0]}" "${args[1]}"
    [[ -z $mode ]] || chmod "$mode" "${args[1]}"
fi
""",
    "cmp": r"""
[[ -e @STATE@/cmp-fails ]] && exit 1
exec @REAL_CMP@ "$@"
""",
    # Fails the worker's own temporary file before it is moved into place.
    "chmod": r"""
[[ -e @STATE@/chmod-fails && ${2:-} == */.install.* ]] && exit 1
exec @REAL_CHMOD@ "$@"
""",
    # Swaps the finished file for a link to an identical copy, as a racing worker could.
    "mv": r"""
@REAL_MV@ "$@" || exit
if [[ -e @STATE@/mv-swaps-in-a-link ]]; then
    dest=${@: -1}
    cp "$dest" "$dest.twin" && ln -sf "$dest.twin" "$dest"
fi
""",
}


def mode_of(path):
    return stat.S_IMODE(path.stat().st_mode)


@unittest.skipUnless(
    BASH and shutil.which("cmp") and shutil.which("id") and os.name == "posix" and os.geteuid() != 0,
    "needs bash, cmp and a non-root POSIX user",
)
class StudioInstallTdarrNodeTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT / "docker/tests" / (".studio-install-test-" + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.build()

    def build(self):
        """A fresh fake Studio: the worker home, the macos/ inputs, plugin modules and stubs."""
        ws = self.workspace
        shutil.rmtree(ws, ignore_errors=True)
        for path in ("state", "bin", "tmp", "daemons", "home/tdarr", "modules", "macos/install"):
            (ws / path).mkdir(parents=True)
        self.home = ws / "home"
        (self.home / "tdarr/Tdarr_Node").write_text("#!/bin/sh\n")
        (self.home / "tdarr/Tdarr_Node").chmod(0o755)
        (self.home / "start-tdarr.sh").write_text("old\n")
        for name in INPUTS:
            shutil.copy(MACOS / name, ws / "macos" / name)
        for name in MODULES:
            (ws / "modules" / name).write_text(f"// {name}\n")
        (ws / "state/loaded").touch()
        self.script = ws / "macos/install/install-tdarr-node.sh"
        self.script.write_text(self.installer_text())
        for name, body in STUBS.items():
            stub = ws / "bin" / name
            body = (
                body.replace("@STATE@", str(ws / "state"))
                .replace("@BIN@", str(ws / "bin"))
                .replace("@REAL_ID@", shutil.which("id"))
                .replace("@REAL_CMP@", shutil.which("cmp"))
                .replace("@REAL_CHMOD@", shutil.which("chmod"))
                .replace("@REAL_MV@", shutil.which("mv"))
            )
            stub.write_text("#!/bin/bash\n" + body + "\n")
            stub.chmod(0o755)

    def installer_text(self):
        """The real installer, pointed at the fake Studio and at bare command names."""
        ws = self.workspace
        # Bare names first, so the workspace path cannot be mistaken for a tool path.
        text = re.sub(r"(?<![\w./-])/(?:usr/)?s?bin/([a-z][\w-]*)", r"\1", INSTALLER.read_text())
        for old, new in (
            ("home=/var/lib/studio-worker", f"home={ws}/home"),
            ("helpers=/Library/PrivilegedHelperTools", f"helpers={ws}/helpers"),
            ("plist=/Library/LaunchDaemons/", f"plist={ws}/daemons/"),
            ("/var/log/studio-tdarr", f"{ws}/log"),
            ("/private/tmp/studio-tdarr-install", f"{ws}/tmp/studio-tdarr-install"),
        ):
            assert old in text, f"{old} is missing from {INSTALLER.name}"
            text = text.replace(old, new)
        return text

    def run_installer(self, *args):
        return subprocess.run(
            [BASH, str(self.script), *args],
            env={**os.environ, "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def flag(self, name, value=""):
        (self.workspace / "state" / name).write_text(value)

    def log(self):
        path = self.workspace / "state/log"
        return path.read_text().splitlines() if path.exists() else []

    def test_stop_boots_the_job_out_disables_it_and_checks_for_leftovers(self):
        result = self.run_installer("--stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no node or encoder processes remain", result.stdout)
        log = self.log()
        self.assertLess(
            log.index(f"launchctl bootout system/{LABEL}"),
            log.index(f"launchctl disable system/{LABEL}"),
        )
        pgrep = next(line for line in log if line.startswith("pgrep"))
        self.assertIn("-u _studio", pgrep)
        self.assertIn(f"{self.home}/mounts/", pgrep)
        # Whisper and Ollama run as the worker too, and Whisper uses ffmpeg.
        self.assertNotIn("ffmpeg", pgrep)

    def test_stop_reports_processes_the_job_left_behind(self):
        self.flag("workers", "4242\n")
        result = self.run_installer("--stop")
        self.assertEqual(result.returncode, 3)
        self.assertIn("4242", result.stderr)
        self.assertNotIn("Stopped and disabled", result.stdout)

    def test_stop_fails_while_launchd_still_has_the_job(self):
        self.flag("bootout-sticks")
        result = self.run_installer("--stop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("still loaded", result.stderr)
        self.assertNotIn(f"launchctl disable system/{LABEL}", self.log())

    def test_stop_works_without_the_node_installed(self):
        shutil.rmtree(self.home / "tdarr")
        self.assertEqual(self.run_installer("--stop").returncode, 0)

    def test_stop_waits_for_the_processes_to_exit(self):
        self.flag("workers", "4242\n")
        self.flag("workers-gone-after", "3")
        result = self.run_installer("--stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stopped and disabled", result.stdout)

    def test_stop_waits_long_enough_for_the_watchdog_to_finish_a_running_probe(self):
        # sleep is stubbed, so each poll stands for a second; a probe of the node's
        # watchdog can run for about 25 s after the node itself is gone.
        self.flag("workers", "4242\n")
        self.flag("workers-gone-after", "40")
        result = self.run_installer("--stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stopped and disabled", result.stdout)

    def test_refuses_to_run_unless_root(self):
        self.flag("not-root")
        for args in ((), ("--stop",)):
            with self.subTest(args):
                result = self.run_installer(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("as root", result.stderr)
        self.assert_nothing_replaced()
        self.assertEqual(self.log(), [])

    def test_rejects_an_unknown_option_before_touching_anything(self):
        result = self.run_installer("--no-such-option")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown option", result.stderr)
        self.assert_nothing_replaced()
        self.assertEqual(self.log(), [])

    def test_refuses_a_privileged_worker_account(self):
        self.flag("studio-root")
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("privileged compute worker", result.stderr)
        self.assert_nothing_replaced()

    def test_refuses_when_the_node_is_not_installed(self):
        shutil.rmtree(self.home / "tdarr")
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not installed", result.stderr)
        self.assert_nothing_replaced()

    def test_a_bad_input_stops_the_install_before_anything_is_replaced(self):
        ws = self.workspace

        def lock_home():
            self.addCleanup(os.chmod, self.home, 0o755)
            self.home.chmod(0o555)

        cases = {
            "missing module": (lambda: (ws / "modules" / MODULES[2]).unlink(), (f"Missing {ws / 'modules' / MODULES[2]}",)),
            "missing mount helper source": (lambda: (ws / "macos/mount-studio-share.c").unlink(), ("Missing", "mount-studio-share.c")),
            "empty start script": (lambda: (ws / "macos/start-tdarr.sh").write_text(""), ("Missing", "start-tdarr.sh")),
            "start script with a syntax error": (lambda: (ws / "macos/start-tdarr.sh").write_text("if then\n"), ("syntax error",)),
            "session script with a syntax error": (lambda: (ws / "macos/start-tdarr-session.sh").write_text("if then\n"), ("syntax error",)),
            "malformed plist": (lambda: self.flag("plutil-fails"), ("Malformed",)),
            "compiler failure": (lambda: self.flag("clang-fails"), ("build failed",)),
            "worker account unusable": (lambda: self.flag("sudo-fails"), ("Cannot run commands as _studio",)),
            "worker commands run as another user": (lambda: self.flag("wrong-user"), ("Cannot run commands as _studio",)),
            # Last: it leaves the fake home read-only until the test's cleanup.
            "worker cannot write to its home": (lock_home, ("cannot write",)),
        }
        for name, (break_it, messages) in cases.items():
            with self.subTest(name):
                self.build()
                break_it()
                result = self.run_installer("--modules", str(ws / "modules"))
                self.assertNotEqual(result.returncode, 0)
                for message in messages:
                    self.assertIn(message, result.stderr)
                self.assert_nothing_replaced()

    def assert_nothing_replaced(self):
        ws = self.workspace
        for untouched in ("helpers", "log"):
            self.assertFalse((ws / untouched).exists(), untouched)
        self.assertEqual(list((ws / "daemons").iterdir()), [])
        self.assertEqual((self.home / "start-tdarr.sh").read_text(), "old\n")
        self.assertFalse((self.home / "mount-studio-share").exists())
        self.assertFalse((self.home / "tdarr/Custom").exists())
        self.assertEqual(list(self.home.glob(".install.*")), [])
        self.assertEqual(list((ws / "tmp").iterdir()), [])

    def test_a_failed_launcher_build_leaves_the_installed_launcher_and_everything_else_alone(self):
        launcher = self.workspace / "helpers" / f"{LABEL}-launcher"
        launcher.parent.mkdir()
        launcher.write_text("OLD\n")
        self.flag("clang-fails", "launcher")
        result = self.run_installer("--modules", str(self.workspace / "modules"), "--replace-launcher")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(launcher.read_text(), "OLD\n")
        self.assertEqual(list(launcher.parent.iterdir()), [launcher])
        self.assertFalse((self.workspace / "log").exists())
        self.assertEqual(list((self.workspace / "daemons").iterdir()), [])
        self.assertEqual((self.home / "start-tdarr.sh").read_text(), "old\n")
        self.assertFalse((self.home / "tdarr/Custom").exists())
        self.assertEqual(list((self.workspace / "tmp").iterdir()), [])

    def test_installs_root_files_as_root_and_the_workers_files_as_the_worker(self):
        ws = self.workspace
        result = self.run_installer("--modules", str(ws / "modules"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Full Disk Access is not granted", result.stderr)
        self.assertIn("Installed.", result.stdout)

        self.assertEqual(mode_of(ws / "helpers" / f"{LABEL}-launcher"), 0o755)
        self.assertEqual(mode_of(ws / "helpers"), 0o755)
        session = ws / "helpers" / f"{LABEL}-session"
        self.assertEqual((session.read_bytes(), mode_of(session)), ((MACOS / "start-tdarr-session.sh").read_bytes(), 0o755))
        plist = ws / "daemons" / f"{LABEL}.plist"
        self.assertEqual((plist.read_bytes(), mode_of(plist)), ((MACOS / f"{LABEL}.plist").read_bytes(), 0o644))
        self.assertEqual(mode_of(ws / "log"), 0o700)

        start = self.home / "start-tdarr.sh"
        self.assertEqual((start.read_bytes(), mode_of(start)), ((MACOS / "start-tdarr.sh").read_bytes(), 0o755))
        self.assertEqual(mode_of(self.home / "mount-studio-share"), 0o755)
        custom = self.home / "tdarr/Custom"
        for name in MODULES:
            self.assertEqual((custom / name).read_text(), f"// {name}\n")
            self.assertEqual(mode_of(custom / name), 0o644)

        installs = [line for line in self.log() if line.startswith("install ")]
        self.assertTrue(installs)
        self.assertEqual([line for line in installs if str(self.home) in line], [], "root wrote into the worker's tree")
        root_owned = [line for line in installs if any(str(ws / name) in line for name in ("helpers", "log", "daemons"))]
        self.assertEqual(len(root_owned), 5, root_owned)
        self.assertTrue(all("-o root -g wheel" in line for line in root_owned), root_owned)
        self.assertIn("sudo-as _studio", self.log())
        self.assertIn("sudo-script-as _studio", self.log())
        self.assertTrue(any(line.startswith("codesign --verify --strict ") for line in self.log()))
        self.assertIn("CDHash=", result.stdout)
        self.assertEqual(list(self.home.glob(".install.*")), [])
        self.assertEqual(list((ws / "tmp").iterdir()), [])

    def test_keeps_an_installed_launcher_unless_told_to_replace_it(self):
        launcher = self.workspace / "helpers" / f"{LABEL}-launcher"
        launcher.parent.mkdir()
        launcher.write_text("OLD\n")
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(launcher.read_text(), "OLD\n")
        self.assertEqual([line for line in self.log() if line.startswith("codesign --force")], [])

        result = self.run_installer("--replace-launcher")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(launcher.read_text(), "built by clang\n")
        self.assertIn("needs the Full Disk Access grant", result.stdout)
        signed = [line for line in self.log() if line.startswith("codesign --force ")]
        self.assertEqual(len(signed), 1)
        self.assertIn("--identifier com.danteb.studio-tdarr-launcher", signed[0])

    def test_warns_when_full_disk_access_is_missing(self):
        self.flag("no-fda")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Full Disk Access is not granted", result.stderr)

    def test_the_worker_replaces_planted_links_instead_of_following_them(self):
        outside = self.workspace / "outside"
        outside.mkdir()
        victim = outside / "victim"
        victim.write_text("precious\n")
        (self.home / "start-tdarr.sh").unlink()
        (self.home / "start-tdarr.sh").symlink_to(victim)
        elsewhere = outside / "dir"
        elsewhere.mkdir()
        (self.home / "tdarr/Custom").symlink_to(elsewhere)

        result = self.run_installer("--modules", str(self.workspace / "modules"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(victim.read_text(), "precious\n")
        self.assertFalse((self.home / "start-tdarr.sh").is_symlink())
        self.assertEqual(list(elsewhere.iterdir()), [])
        custom = self.home / "tdarr/Custom"
        self.assertTrue(custom.is_dir() and not custom.is_symlink())
        self.assertEqual(sorted(path.name for path in custom.iterdir()), sorted(MODULES))
        moved = list((self.home / "tdarr").glob("Custom.superseded.*"))
        self.assertEqual([path.is_symlink() for path in moved], [True])
        self.assertIn("Moved the previous plugin directory", result.stdout)

    def test_a_plugin_directory_that_is_not_a_directory_is_moved_aside(self):
        (self.home / "tdarr/Custom").write_text("in the way\n")
        result = self.run_installer("--modules", str(self.workspace / "modules"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / "tdarr/Custom").is_dir())
        self.assertEqual(len(list((self.home / "tdarr").glob("Custom.superseded.*"))), 1)

    def test_an_existing_plugin_directory_of_the_worker_is_updated_in_place(self):
        custom = self.home / "tdarr/Custom"
        custom.mkdir()
        (custom / "keep.cjs").write_text("keep\n")
        result = self.run_installer("--modules", str(self.workspace / "modules"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((custom / "keep.cjs").read_text(), "keep\n")
        self.assertEqual(list((self.home / "tdarr").glob("Custom.superseded.*")), [])
        self.assertEqual((custom / MODULES[0]).read_text(), f"// {MODULES[0]}\n")

    def test_a_failed_worker_side_copy_fails_the_install_and_leaves_no_temp_file(self):
        self.flag("cmp-fails")
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not install", result.stderr)
        self.assertEqual(list(self.home.glob(".install.*")), [])

    def test_a_worker_side_step_that_fails_before_the_move_leaves_no_temp_file(self):
        self.flag("chmod-fails")
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not install", result.stderr)
        self.assertEqual(list(self.home.glob(".install.*")), [])

    def test_a_destination_that_turns_into_a_link_fails_the_install(self):
        self.flag("mv-swaps-in-a-link")
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not install", result.stderr)

    def test_start_unloads_then_retries_bootstrap_until_launchd_accepts_it(self):
        self.flag("bootstrap-fails", "2")
        result = self.run_installer("--start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Started {LABEL}", result.stdout)
        verbs = [line.split()[1] for line in self.log() if line.startswith("launchctl ")]
        self.assertEqual(verbs.count("bootstrap"), 3)
        self.assertLess(verbs.index("bootout"), verbs.index("enable"))
        self.assertLess(verbs.index("enable"), verbs.index("bootstrap"))

    def test_start_gives_up_after_three_failed_bootstraps(self):
        self.flag("bootstrap-fails", "3")
        result = self.run_installer("--start")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed three times", result.stderr)

    def test_start_fails_when_the_job_is_not_loaded_afterwards(self):
        self.flag("bootstrap-no-load")
        result = self.run_installer("--start")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not loaded", result.stderr)
        self.assertNotIn("Started", result.stdout)

    def test_avoids_bash_4_features_because_macos_ships_bash_3_2(self):
        text = INSTALLER.read_text()
        self.assertIsNone(re.search(r"mapfile|readarray|declare -A|\$\{[^}]*(,,|\^\^)|&>>|\|&|\[\[ -v ", text))


if __name__ == "__main__":
    unittest.main()
