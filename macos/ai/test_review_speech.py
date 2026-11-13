import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import review_speech
from review_speech import metric, read_cues


class ReviewTests(unittest.TestCase):
    def test_srt_keeps_invalid_timing_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generated.srt"
            path.write_text(
                "1\n00:00:02,000 --> 00:00:01,000\nHello\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\n...\n",
                encoding="utf-8",
            )
            result = metric([(0, 3, "Hello")], read_cues(path))
        self.assertEqual(result["invalid_duration"], 1)
        self.assertEqual(result["backward_start"], 1)
        self.assertEqual(result["nonword_cues"], 1)
        self.assertEqual(result["reference_word_cues_with_word_overlap"], 0)

    def test_ass_excludes_animated_signs_and_preserves_commas(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.ass"
            path.write_text(
                "Dialogue: 0,0:00:01.00,0:00:02.00,Signs,,0,0,0,,Animated text\n"
                "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,"
                "{\\i1}Hello,\\Nworld\n", encoding="utf-8")
            self.assertEqual(read_cues(path), [(2, 3, "Hello, world")])

    def test_malformed_srt_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generated.srt"
            path.write_text("Error: inference failed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_cues(path)

    def test_audio_boundary_is_measured_independently_of_reference(self):
        result = metric([(0, 1, "Hello")], [(1, 3, "Invented")], audio_duration=2)
        self.assertEqual(result["cues_past_audio_end"], 1)
        self.assertEqual(result["max_end_seconds"], 3)

    def test_explicit_missing_studio_output_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.argv", [
                "review_speech.py", directory, "telugu", "--studio-file",
                str(Path(directory) / "missing.srt"),
            ]), self.assertRaises(SystemExit) as error:
                review_speech.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
