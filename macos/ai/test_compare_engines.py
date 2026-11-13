import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import compare_engines


class CompareTests(unittest.TestCase):
    def test_incomplete_private_manifest_fails_before_remote_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text('{"episodes": {"english": {}}}', encoding="utf-8")
            with patch.object(compare_engines, "ssh") as ssh:
                with self.assertRaisesRegex(ValueError, "Source manifest"):
                    compare_engines.prepare(path)
        ssh.assert_not_called()

    def test_extraction_uses_private_manifest_paths(self):
        episodes = {
            kind: {
                "path": f"/private/media/{kind} input.mkv",
                "audio_stream": 1, "reference_stream": 4,
                "reference_format": "srt" if kind == "english" else "ass",
            } for kind in compare_engines.KINDS
        }
        probes = [
            json.dumps({"streams": [{"index": 1, "tags": {"language": language}}]}).encode()
            for language in ("eng", "jpn", "tel")
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps({"episodes": episodes}), encoding="utf-8")
            with patch.object(compare_engines, "ssh"), patch.object(
                compare_engines, "capture", side_effect=probes
            ), patch.object(
                compare_engines, "transfer", return_value={"bytes": 2, "sha256": "test"}
            ) as transfer, patch.object(compare_engines, "save"), patch("builtins.print"):
                compare_engines.prepare(path)
        for index, kind in enumerate(compare_engines.KINDS):
            command, filename = transfer.call_args_list[index * 2].args
            self.assertIn(f"'/private/media/{kind} input.mkv'", command)
            self.assertEqual(filename, f"{kind}.pcm")

    def test_existing_output_fails_before_reading_audio(self):
        with patch.object(compare_engines, "ssh", side_effect=subprocess.CalledProcessError(
            1, "output preflight"
        )), patch.object(compare_engines, "capture") as capture:
            with self.assertRaises(subprocess.CalledProcessError):
                compare_engines.run_engine("studio", "english")
        capture.assert_not_called()

    def test_changed_pcm_fails_before_any_inference(self):
        manifest = {"episodes": {"english": {
            "task": "transcribe", "language": "en",
            "pcm": {"bytes": 2, "sha256": hashlib.sha256(b"\0\0").hexdigest()},
        }}}
        with patch.object(compare_engines, "ssh") as ssh, patch.object(
            compare_engines, "capture", side_effect=[json.dumps(manifest).encode(), b"\1\0"]
        ), patch.object(compare_engines, "save") as save:
            with self.assertRaisesRegex(RuntimeError, "PCM checksum changed"):
                compare_engines.run_engine("server", "english")
        self.assertEqual(ssh.call_count, 1)  # Output-existence preflight only.
        save.assert_not_called()

    def test_error_response_is_saved_as_diagnostic_not_subtitle(self):
        raw = b"\0\0"
        digest = hashlib.sha256(raw).hexdigest()
        manifest = {"episodes": {"english": {
            "task": "transcribe", "language": "en",
            "pcm": {"bytes": 2, "sha256": digest},
        }}}
        response = SimpleNamespace(
            stdout=b'{"detail":"invalid SRT"}',
            stderr=json.dumps({"status": 422, "pcm_sha256": digest}).encode(),
        )
        with patch.object(compare_engines, "capture", side_effect=[
            json.dumps(manifest).encode(), raw
        ]), patch.object(compare_engines, "ssh", return_value=response), patch.object(
            compare_engines, "save"
        ) as save, patch("builtins.print"):
            compare_engines.run_engine("studio", "english")
        self.assertEqual(save.call_args_list[0].args[0], "english-studio.error")
        self.assertEqual(save.call_args_list[1].args[0], "english-studio.json")


if __name__ == "__main__":
    unittest.main()
