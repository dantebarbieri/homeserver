import io
import json
from pathlib import Path
import re
import unittest
from urllib.request import urlopen
import zipfile

from jsonschema import Draft7Validator
from referencing import Registry, Resource
import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
GATE_ID = "homeserver-english-anime-audio"
SERVICES = ("sonarr", "radarr")
RESOLUTIONS = (480, 576, 720, 1080, 2160)


class ConfigLoader(yaml.SafeLoader):
    pass


ConfigLoader.add_constructor("!secret", lambda loader, node: "validation-placeholder")


def load_yaml(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=ConfigLoader)


def download_archive(url):
    with urlopen(url, timeout=120) as response:
        return zipfile.ZipFile(io.BytesIO(response.read()))


def matches_english_audio(title, custom_format):
    return all(
        bool(re.search(spec["fields"]["value"], title)) != spec["negate"]
        for spec in custom_format["specifications"]
    )


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_yaml(ROOT / "recyclarr.yml")
        cls.settings = load_yaml(ROOT / "settings.yml")
        cls.profiles = {}
        cls.assignments = {}
        cls.custom_format = json.loads(
            (ROOT / "custom-formats" / "english-anime-audio.json").read_text()
        )
        cls.guide = {service: {} for service in SERVICES}
        with download_archive(
            "https://codeload.github.com/TRaSH-Guides/Guides/zip/refs/heads/master"
        ) as archive:
            for name in archive.namelist():
                for service in SERVICES:
                    if f"/docs/json/{service}/cf/" in name and name.endswith(".json"):
                        resource = json.loads(archive.read(name))
                        cls.guide[service][resource["trash_id"]] = resource
        for service in SERVICES:
            cls.guide[service][GATE_ID] = cls.custom_format
            directory = ROOT / "includes" / service
            cls.profiles[service] = load_yaml(directory / "quality-profiles.yml")["quality_profiles"]
            cls.assignments[service] = load_yaml(directory / "custom-formats.yml")["custom_formats"]

        image = load_yaml(REPO / "docker" / "compose.starr.yml")["services"]["recyclarr"]["image"]
        cls.version = image.rsplit(":", 1)[1]
        cls.schemas = {}
        with download_archive(
            f"https://codeload.github.com/recyclarr/recyclarr/zip/refs/tags/v{cls.version}"
        ) as archive:
            for name in archive.namelist():
                if "/schemas/" in name and name.endswith(".json"):
                    schema = json.loads(archive.read(name))
                    relative = name.split("/schemas/", 1)[1]
                    schema["$id"] = f"https://schemas.recyclarr.dev/{cls.version}/{relative}"
                    cls.schemas[relative] = schema
        cls.registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in cls.schemas.values()
        )

    def scores(self, service, profile):
        result = {}
        for block in self.assignments[service]:
            self.assertTrue(block["trash_ids"], "Remove empty custom-format blocks")
            for target in block.get("assign_scores_to", []):
                if target["name"] != profile["name"]:
                    continue
                for trash_id in block["trash_ids"]:
                    self.assertNotIn(
                        trash_id, result, f"Duplicate CF/profile assignment: {profile['name']} / {trash_id}"
                    )
                    guide_scores = self.guide[service][trash_id].get("trash_scores", {})
                    score = target.get(
                        "score",
                        guide_scores.get(profile.get("score_set"), guide_scores.get("default", 0)),
                    )
                    # Unscored guide formats stay at zero because every profile resets unmatched scores.
                    result[trash_id] = score
        return result

    def test_versioned_schemas_and_provider_wiring(self):
        workflow = load_yaml(REPO / ".github" / "workflows" / "recyclarr-validate.yml")
        self.assertIn(
            f"ghcr.io/recyclarr/recyclarr:{self.version}",
            json.dumps(workflow),
            "CI must use the same Recyclarr version as Compose",
        )
        for filename, data in (("config-schema.json", self.main), ("settings-schema.json", self.settings)):
            Draft7Validator(self.schemas[filename], registry=self.registry).validate(data)
        providers = self.settings["resource_providers"]
        self.assertEqual({provider["service"] for provider in providers}, set(SERVICES))
        for provider in providers:
            self.assertEqual(provider["type"], "custom-formats")
            self.assertNotIn("replace_default", provider)
            self.assertEqual(
                list((ROOT / provider["path"]).glob("*.json")),
                [ROOT / "custom-formats" / "english-anime-audio.json"],
            )
        resolved = {}
        for service, instances in self.main.items():
            resolved[service] = {}
            for name, instance in instances.items():
                expanded = dict(instance)
                for include in expanded.pop("include"):
                    expanded.update(load_yaml(ROOT / "includes" / include["config"]))
                resolved[service][name] = expanded
        Draft7Validator(self.schemas["config-schema.json"], registry=self.registry).validate(resolved)

    def test_profile_names_score_sets_and_assignments(self):
        for service in SERVICES:
            expected = {
                base + suffix
                for base in (
                    "SD - 480p", "SD - 576p", "HD - 720p", "HD - 1080p", "4K UHD - 2160p",
                    *(f"At most {resolution}p" for resolution in RESOLUTIONS),
                )
                for suffix in ("", " Anime", " Anime (Dub)")
            }
            profiles = self.profiles[service]
            self.assertEqual(len(profiles), 30)
            self.assertEqual({profile["name"] for profile in profiles}, expected)
            for block in self.assignments[service]:
                for target in block["assign_scores_to"]:
                    self.assertIn(target["name"], expected)
                for trash_id in block["trash_ids"]:
                    self.assertIn(trash_id, self.guide[service])
            for profile in profiles:
                with self.subTest(service=service, profile=profile["name"]):
                    scores = self.scores(service, profile)
                    if "Anime" in profile["name"]:
                        self.assertEqual(profile["score_set"], f"anime-{service}")
                    else:
                        self.assertNotIn("score_set", profile)
                    self.assertTrue(profile["reset_unmatched_scores"]["enabled"])
                    self.assertTrue(scores)

    def test_quality_order_and_resolution_limits(self):
        for service in SERVICES:
            for profile in self.profiles[service]:
                with self.subTest(service=service, profile=profile["name"]):
                    ceiling = int(re.search(r"(\d+)p", profile["name"])[1])
                    anime = "Anime" in profile["name"]
                    qualities = profile["qualities"]
                    flattened = [
                        name for quality in qualities
                        for name in quality.get("qualities", [quality["name"]])
                    ]
                    self.assertEqual(len(flattened), len(set(flattened)))
                    self.assertEqual(profile["quality_sort"], "top")
                    self.assertEqual(profile["upgrade"]["until_quality"], qualities[0]["name"])
                    self.assertTrue(profile["upgrade"]["allowed"])
                    expected_order = []
                    for resolution in reversed(RESOLUTIONS):
                        if resolution > ceiling or (
                            not profile["name"].startswith("At most") and resolution != ceiling
                        ):
                            continue
                        if resolution == 576:
                            expected_order.append({"Bluray-576p"})
                            continue
                        bluray = f"Bluray-{resolution}p"
                        if resolution >= 1080:
                            remux = f"{bluray} Remux" if service == "sonarr" else f"Remux-{resolution}p"
                            if anime:
                                expected_order.append({remux, bluray})
                            else:
                                expected_order.extend([{remux}, {bluray}])
                        else:
                            expected_order.append({bluray})
                        web = {f"WEBDL-{resolution}p", f"WEBRip-{resolution}p"}
                        hdtv = {f"HDTV-{resolution}p"} if resolution >= 720 else set()
                        if anime:
                            expected_order.append(web | hdtv)
                        else:
                            expected_order.append(web)
                            if hdtv:
                                expected_order.append(hdtv)
                    if profile["name"].startswith("At most"):
                        expected_order.extend([{"DVD", "DVD-R"} if service == "radarr" else {"DVD"}, {"SDTV"}])
                    self.assertEqual(
                        [set(quality.get("qualities", [quality["name"]])) for quality in qualities],
                        expected_order,
                    )

    def test_dub_eligibility_rejections_and_upgrade_headroom(self):
        rejected = {"Anime LQ Groups", "Anime Raws", "VOSTFR", "AV1", "BR-DISK", "LQ", "LQ (Release Title)", "Extras"}
        for service in SERVICES:
            for profile in self.profiles[service]:
                with self.subTest(service=service, profile=profile["name"]):
                    scores = self.scores(service, profile)
                    named = {self.guide[service][key]["name"]: score for key, score in scores.items()}
                    if not profile["name"].endswith("(Dub)"):
                        self.assertNotIn(GATE_ID, scores)
                        self.assertEqual(profile["upgrade"]["until_score"], 10000)
                        if "Anime" in profile["name"]:
                            self.assertEqual(named["Dubs Only"], -10000)
                            self.assertEqual(named["Anime Dual Audio"], 0)
                            self.assertEqual(named["AV1"], -10000)
                        continue
                    self.assertEqual(profile["min_format_score"], 20000)
                    self.assertEqual(scores[GATE_ID], 20000)
                    self.assertEqual(named["Dubs Only"], 0)
                    self.assertEqual(named["Anime Dual Audio"], 0)
                    positives = sum(max(0, score) for key, score in scores.items() if key != GATE_ID)
                    self.assertLess(positives, profile["min_format_score"], "Sub-only releases must not qualify")
                    maximum = scores[GATE_ID] + positives
                    self.assertEqual(profile["upgrade"]["until_score"], 40000)
                    self.assertLess(maximum, profile["upgrade"]["until_score"], "Dub marker must not end upgrades")
                    unwanted = rejected | ({"3D", "Upscaled"} if service == "radarr" else set())
                    for name in unwanted:
                        self.assertEqual(named[name], -100000)
                        self.assertLess(maximum + named[name], profile["min_format_score"])
                    self.assertGreaterEqual(scores[GATE_ID], profile["min_format_score"])
                    tier1 = named["Anime BD Tier 01"]
                    tier2 = named["Anime BD Tier 02"]
                    self.assertGreater(scores[GATE_ID] + tier1, scores[GATE_ID] + tier2)
                    self.assertLess(scores[GATE_ID] + tier1, profile["upgrade"]["until_score"])

    def test_sdr_is_allowed_and_standard_dv_fallback_protection_remains(self):
        for service in SERVICES:
            for profile in self.profiles[service]:
                scores = self.scores(service, profile)
                named = {self.guide[service][key]["name"]: score for key, score in scores.items()}
                self.assertNotIn("SDR", named)
                self.assertNotIn("SDR (no WEBDL)", named)
                if profile["name"] in ("4K UHD - 2160p", "At most 2160p"):
                    self.assertEqual(named["DV (w/o HDR fallback)"], -10000)
                    self.assertGreater(named["HDR"], 0)

    def test_english_audio_matching(self):
        self.assertEqual(self.custom_format["trash_id"], GATE_ID)
        self.assertTrue(self.custom_format["includeCustomFormatWhenRenaming"])
        for spec in self.custom_format["specifications"]:
            self.assertEqual(spec["implementation"], "ReleaseTitleSpecification")
            self.assertTrue(spec["required"])
        cases = json.loads((ROOT / "tests" / "english-audio-cases.json").read_text())
        for case in cases:
            with self.subTest(title=case["title"]):
                self.assertEqual(
                    matches_english_audio(case["title"], self.custom_format), case["matches"]
                )


if __name__ == "__main__":
    unittest.main()
