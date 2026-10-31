import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docker/scripts/setup-prowlarr-definitions.sh"
PROGRAMS = ROOT / "docker/prowlarr"
AWK = shutil.which("awk")

# Runs `docker exec [-i] prowlarr ...` locally with /config mapped to CONFIG_ROOT.
MOCK_DOCKER = r"""#!/usr/bin/env python3
import json
import os
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] != ["exec"]:
    sys.exit("Unexpected Docker command")
args = args[1:]
if args[:1] == ["-i"]:
    args = args[1:]
if args[:1] != ["prowlarr"]:
    sys.exit("Unexpected container")
command = [value.replace("/config", os.environ["CONFIG_ROOT"]) for value in args[1:]]
if command[:2] == ["sh", "-c"] and "api/v1/command" in command[2]:
    sys.exit(int(os.environ.get("FAIL_RELOAD", "0")))
sys.exit(subprocess.run(command).returncode)
"""


def nyaa_definition():
    mappings = "".join(
        f'    - {{id: 1_{index}, cat: {category}, desc: "Anime {index}"}}\n'
        for category in ("TV/Anime", "Movies/Other")
        for index in range(5)
    )
    options = "".join(
        f'      {group}_{index}: "Category {group}_{index}"\n'
        for group in range(3)
        for index in range(5)
    )
    return (
        "---\nid: nyaasi\nname: Nyaa.si\nrequestDelay: 2\n"
        "caps:\n  categorymappings:\n"
        + mappings
        + '    - {id: 2_0, cat: Audio, desc: "Audio"}\n'
        + '    - {id: 4_0, cat: TV, desc: "Live Action"}\n'
        + "  modes:\n    search: [q]\n    tv-search: [q, season, ep]\n"
        + "    movie-search: [q]\n    music-search: [q]\n    book-search: [q]\n"
        + "settings:\n  - name: cat-id\n    type: select\n"
        + "    default: 0_0\n    options:\n"
        + options
        + "  - name: sort\n    default: id\n    options:\n      id: created\n"
        + "search:\n  paths:\n    - path: /\n      inputs:\n"
        + '        q: "{{ .Keywords }}"\n'
        + "    - path: /\n      inputs:\n"
        + '        q: "{{ re_replace .Keywords \\"0\\" \\"\\" }}"\n'
        + '        p: "{{ if .Keywords }}{{ else }}2{{ end }}"\n'
        + "  fields:\n    title:\n      selector: a\n"
    )


def archive_definition():
    return (
        "---\nid: internetarchive\nname: Internet Archive\n"
        "links:\n  - https://archive.org/\n"
        "caps:\n  modes:\n    search: [q]\n"
        "search:\n  paths:\n    - path: advancedsearch.php\n      response:\n        type: json\n"
        "  rows:\n    selector: $.response.docs\n"
    )


def transform(program, source):
    text = (PROGRAMS / program).read_text()
    return subprocess.run(
        [AWK, text], input=source, text=True, capture_output=True, timeout=10
    )


@unittest.skipUnless(AWK, "awk is not installed")
class NyaaAnimeDefinitionTests(unittest.TestCase):
    def transform(self, source):
        return transform("nyaasi-anime-homeserver.awk", source)

    def test_only_unrelated_capabilities_are_removed(self):
        result = self.transform(nyaa_definition())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("id: nyaasi-anime-homeserver\n", result.stdout)
        self.assertIn("name: Nyaa.si (anime homeserver)\n", result.stdout)
        self.assertEqual(result.stdout.count("cat: TV/Anime,"), 5)
        self.assertEqual(result.stdout.count("cat: Movies/Other,"), 5)
        self.assertNotIn("cat: Audio,", result.stdout)
        self.assertNotIn("cat: TV,", result.stdout)
        self.assertNotIn("music-search:", result.stdout)
        self.assertNotIn("book-search:", result.stdout)
        for mode in ("search: [q]", "tv-search: [q, season, ep]", "movie-search: [q]"):
            self.assertIn(mode, result.stdout)

    def test_anime_default_and_dropdown_are_consistent(self):
        result = self.transform(nyaa_definition())
        self.assertEqual(result.returncode, 0, result.stderr)
        category = result.stdout.split("  - name: cat-id\n")[1].split("  - name: sort")[0]
        self.assertIn("    default: 1_0\n", category)
        self.assertEqual(category.count("      1_"), 5)
        self.assertNotIn("      0_", category)
        self.assertNotIn("      2_", category)

    def test_search_variants_rss_and_parser_are_unchanged(self):
        source = nyaa_definition()
        result = self.transform(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            source.split("\nsearch:\n", 1)[1], result.stdout.split("\nsearch:\n", 1)[1]
        )
        self.assertIn("requestDelay: 2\n", result.stdout)
        self.assertIn("  - name: sort\n    default: id\n", result.stdout)

    def test_unexpected_upstream_structure_fails(self):
        for source in (
            "",
            nyaa_definition().replace("id: nyaasi\n", "id: renamed\n"),
            nyaa_definition().replace("  - name: cat-id\n", "  - name: category\n"),
            nyaa_definition().replace("cat: Movies/Other,", "cat: Movies,"),
        ):
            with self.subTest(source=source[:80]):
                result = self.transform(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected Nyaa definition structure", result.stderr)


@unittest.skipUnless(AWK, "awk is not installed")
class InternetArchiveDefinitionTests(unittest.TestCase):
    def transform(self, source):
        return transform("internetarchive-homeserver.awk", source)

    def test_only_identity_and_search_user_agent_change(self):
        source = archive_definition()
        result = self.transform(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (
            source.replace("id: internetarchive\n", "id: internetarchive-homeserver\n")
            .replace("name: Internet Archive\n", "name: Internet Archive (homeserver)\n")
            .replace(
                "search:\n",
                'search:\n  headers:\n    User-Agent: ["Mozilla/5.0 (X11; Linux x86_64; '
                'rv:128.0) Gecko/20100101 Firefox/128.0"]\n',
            )
        )
        self.assertEqual(result.stdout, expected)

    def test_upstream_headers_need_review(self):
        for source in (
            archive_definition().replace(
                "search:\n", 'search:\n  headers:\n    User-Agent: ["Something"]\n'
            ),
            archive_definition().replace("search:\n", "search:\n  headers:\n    Accept: [x]\n"),
        ):
            with self.subTest(source=source):
                result = self.transform(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("review whether the User-Agent workaround", result.stderr)

    def test_unexpected_upstream_structure_fails(self):
        for source in (
            "",
            archive_definition().replace("id: internetarchive\n", "id: renamed\n"),
            archive_definition().replace("search:\n", "query:\n"),
        ):
            with self.subTest(source=source[:80]):
                result = self.transform(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected Internet Archive definition structure", result.stderr)


@unittest.skipUnless(AWK and os.name == "posix", "needs awk and a POSIX shell")
class SetupProwlarrDefinitionsTests(unittest.TestCase):
    def setUp(self):
        # Keep all generated fixtures inside the checkout, never in a system temp directory.
        self.workspace = ROOT / "docker/tests" / (".prowlarr-test-" + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, self.workspace)
        bin_dir = self.workspace / "bin"
        bin_dir.mkdir(parents=True)
        docker = bin_dir / "docker"
        docker.write_text(MOCK_DOCKER)
        docker.chmod(0o755)
        self.config = self.workspace / "config"
        self.definitions = self.config / "Definitions"
        self.custom = self.definitions / "Custom"
        self.definitions.mkdir(parents=True)
        (self.definitions / "internetarchive.yml").write_text(archive_definition())
        (self.definitions / "nyaasi.yml").write_text(nyaa_definition())
        self.call_log = self.workspace / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "CONFIG_ROOT": str(self.config),
            "CALL_LOG": str(self.call_log),
        }

    def run_script(self, *args, **env):
        self.call_log.write_text("")
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def reloads(self):
        calls = [json.loads(line) for line in self.call_log.read_text().splitlines()]
        return sum("api/v1/command" in call[-1] for call in calls)

    def installed(self):
        return {path.name: path.read_text() for path in sorted(self.custom.glob("*"))}

    def test_installs_then_leaves_current_definitions_alone(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self.installed()
        self.assertEqual(
            sorted(files), ["internetarchive-homeserver.yml", "nyaasi-anime-homeserver.yml"]
        )
        self.assertIn("id: internetarchive-homeserver\n", files["internetarchive-homeserver.yml"])
        self.assertIn("id: nyaasi-anime-homeserver\n", files["nyaasi-anime-homeserver.yml"])
        self.assertIn("internetarchive-homeserver: updated", result.stdout)
        self.assertEqual(self.reloads(), 1)

        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.installed(), files)
        self.assertIn("internetarchive-homeserver: up to date", result.stdout)
        self.assertIn("nyaasi-anime-homeserver: up to date", result.stdout)
        self.assertEqual(self.reloads(), 0)

    def test_follows_upstream_changes_and_shows_the_diff(self):
        self.assertEqual(self.run_script().returncode, 0)
        upstream = self.definitions / "nyaasi.yml"
        upstream.write_text(upstream.read_text().replace("requestDelay: 2", "requestDelay: 3"))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-requestDelay: 2\n+requestDelay: 3\n", result.stdout)
        self.assertIn("nyaasi-anime-homeserver: updated", result.stdout)
        self.assertIn("internetarchive-homeserver: up to date", result.stdout)
        self.assertIn("requestDelay: 3", self.installed()["nyaasi-anime-homeserver.yml"])
        self.assertEqual(self.reloads(), 1)

    def test_dry_run_changes_nothing(self):
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nyaasi-anime-homeserver: would update", result.stdout)
        self.assertFalse(self.custom.exists() and any(self.custom.iterdir()))
        self.assertEqual(self.reloads(), 0)

    def test_unexpected_upstream_keeps_the_installed_copy(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = self.installed()
        upstream = self.definitions / "nyaasi.yml"
        upstream.write_text(upstream.read_text().replace("  - name: cat-id\n", "  - name: x\n"))
        archive = self.definitions / "internetarchive.yml"
        archive.write_text(archive.read_text() + "# upstream change\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("nyaasi-anime-homeserver: could not derive it", result.stderr)
        after = self.installed()
        self.assertEqual(after["nyaasi-anime-homeserver.yml"], before["nyaasi-anime-homeserver.yml"])
        self.assertTrue(after["internetarchive-homeserver.yml"].endswith("# upstream change\n"))
        self.assertEqual(self.reloads(), 1)
        self.assertFalse([path for path in self.custom.iterdir() if path.name.startswith(".")])

    def test_failed_reload_is_reported(self):
        result = self.run_script(FAIL_RELOAD="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not ask Prowlarr to reload definitions", result.stderr)
        self.assertEqual(len(self.installed()), 2)

    def test_rejects_unknown_arguments(self):
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.call_log.read_text(), "")


if __name__ == "__main__":
    unittest.main()
