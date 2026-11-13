import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
from fastapi import HTTPException

import whisper_adapter
from whisper_worker import decoding_options, read_pcm, validate_srt


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        whisper_adapter.job_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=whisper_adapter.app),
            base_url="http://127.0.0.1",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_pcm_srt_and_opaque_video_label(self):
        raw = b"\x00\x80\x00\x00\xff\x7f"

        async def fake_worker(mode, path, language):
            self.assertEqual((mode, language), ("translate", "te"))
            with open(path, "rb") as audio:
                self.assertEqual(audio.read(), raw)
            return b"1\n00:00:00,000 --> 00:00:01,000\nHello.\n\n"

        with patch.object(whisper_adapter, "run_worker", fake_worker):
            response = await self.client.post(
                "/asr",
                params={
                    "task": "translate", "language": "te", "output": "srt",
                    "encode": "false", "video_file": "/unreadable/private/path",
                },
                files={"audio_file": ("audio", raw, "application/octet-stream")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("00:00:00,000 --> 00:00:01,000", response.text)

    async def test_detect_language_response(self):
        async def fake_worker(mode, path, language):
            self.assertEqual((mode, language), ("detect", None))
            return b'{"language_code":"ja","detected_language":"japanese","confidence":0.9}'

        with patch.object(whisper_adapter, "run_worker", fake_worker):
            response = await self.client.post(
                "/detect-language?encode=false",
                files={"audio_file": ("audio", b"\x01\x00")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["language_code"], "ja")
        self.assertEqual(response.json()["detected_language"], "japanese")

    async def test_invalid_inputs_are_rejected(self):
        cases = [
            ("/asr?task=bad&output=srt&encode=false", b"\x00\x00"),
            ("/asr?task=transcribe&language=../x&output=srt&encode=false", b"\x00\x00"),
            ("/asr?task=transcribe&output=json&encode=false", b"\x00\x00"),
            ("/detect-language?encode=true", b"\x00\x00"),
            ("/detect-language?encode=false", b""),
            ("/detect-language?encode=false", b"\x00"),
        ]
        with patch.object(whisper_adapter, "run_worker") as worker:
            for url, raw in cases:
                with self.subTest(url=url, size=len(raw)):
                    response = await self.client.post(
                        url, files={"audio_file": ("audio", raw)}
                    )
                    self.assertEqual(response.status_code, 400)
            worker.assert_not_called()
        with patch.object(whisper_adapter, "MAX_AUDIO", 2):
            response = await self.client.post(
                "/detect-language?encode=false", files={"audio_file": ("audio", b"\0" * 4)}
            )
        self.assertEqual(response.status_code, 413)
        response = await self.client.post(
            "/detect-language?encode=false", data={"audio_file": "not a file"}
        )
        self.assertEqual(response.status_code, 415)

    async def test_declared_body_limit_is_enforced(self):
        with patch.object(whisper_adapter, "MAX_BODY", 32):
            response = await self.client.post(
                "/detect-language?encode=false", files={"audio_file": ("audio", b"\0\0")}
            )
        self.assertEqual(response.status_code, 413)

    async def test_busy_rejects_without_launching_another_job(self):
        started = asyncio.Event()
        finish = asyncio.Event()

        async def fake_worker(mode, path, language):
            started.set()
            await finish.wait()
            return b'{"language_code":"en","detected_language":"english"}'

        with patch.object(whisper_adapter, "run_worker", fake_worker):
            first = asyncio.create_task(self.client.post(
                "/detect-language?encode=false", files={"audio_file": ("audio", b"\0\0")}
            ))
            await started.wait()
            second = await self.client.post(
                "/detect-language?encode=false", files={"audio_file": ("audio", b"\0\0")}
            )
            self.assertEqual(second.status_code, 503)
            finish.set()
            self.assertEqual((await first).status_code, 200)

    async def test_worker_failure_is_not_subtitle_success(self):
        async def fail(mode, path, language):
            raise HTTPException(500, "Speech worker failed")

        with patch.object(whisper_adapter, "run_worker", fail):
            response = await self.client.post(
                "/detect-language?encode=false", files={"audio_file": ("audio", b"\0\0")}
            )
            self.assertEqual(response.status_code, 500)
        self.assertFalse(whisper_adapter.job_lock.locked())

    async def test_invalid_srt_worker_exit_is_explicit(self):
            process = AsyncMock()
            process.returncode = 65
            process.communicate.return_value = (b"", None)
            with patch("whisper_adapter.asyncio.create_subprocess_exec", return_value=process):
                with self.assertRaises(HTTPException) as error:
                    await whisper_adapter.run_worker("transcribe", "audio.pcm", "en")
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(error.exception.detail, "Speech worker produced invalid SRT")


class WorkerTests(unittest.TestCase):
    def test_signed_little_endian_pcm_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "audio.pcm")
            with open(path, "wb") as audio:
                audio.write(b"\x00\x80\x00\x00\xff\x7f")
            np.testing.assert_allclose(read_pcm(path), [-1.0, 0.0, 32767 / 32768])
            self.assertEqual(len(read_pcm(path, 1)), 1)

    def test_decoder_reset_is_limited_to_explicit_english_transcription(self):
        self.assertEqual(
            decoding_options("transcribe", "en"), {"condition_on_previous_text": False}
        )
        for mode, language in (("translate", "en"), ("translate", "ja"),
                               ("translate", "te"), ("transcribe", "ja"),
                               ("transcribe", "")):
            self.assertEqual(decoding_options(mode, language), {})

    def test_srt_timing_is_validated_without_rewriting(self):
        validate_srt(
            "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\nWorld\n"
        )
        for text in (
            "1\n00:00:02,000 --> 00:00:01,000\nHello\n",
            "1\n00:00:02,000 --> 00:00:02,000\nHello\n",
            "1\n00:00:02,000 --> 00:00:03,000\nHello\n\n"
            "2\n00:00:01,000 --> 00:00:04,000\nWorld\n",
            "1\n00:60:00,000 --> 01:00:01,000\nHello\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_srt(text)


if __name__ == "__main__":
    unittest.main()
