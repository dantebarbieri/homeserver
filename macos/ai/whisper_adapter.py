"""Loopback-only Bazarr PCM/SRT subset of the Whisper ASR API."""

import asyncio
import logging
import os
from pathlib import Path
import sys
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

MAX_AUDIO = 2 * 60 * 60 * 16000 * 2
MAX_BODY = MAX_AUDIO + 256 * 1024
UPLOAD_TIMEOUT = 120
JOB_TIMEOUT = 2 * 60 * 60
LANGUAGES = frozenset(
    "en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms "
    "cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn "
    "et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be "
    "tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha "
    "ba jw su yue".split()
)
logger = logging.getLogger("studio_whisper")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
job_lock = asyncio.Lock()
WORKER = Path(__file__).with_name("whisper_worker.py")


@app.middleware("http")
async def bound_request(request, call_next):
    if request.url.path not in {"/asr", "/detect-language"} or request.method != "POST":
        return await call_next(request)
    try:
        length = int(request.headers["content-length"])
    except (KeyError, ValueError):
        return Response("Content-Length required", status_code=411)
    if length <= 0 or length > MAX_BODY:
        return Response("Request too large", status_code=413)
    if job_lock.locked():
        return Response("Speech worker busy", status_code=503)
    await job_lock.acquire()
    received = 0
    original_receive = request.receive

    async def limited_receive():
        nonlocal received
        message = await original_receive()
        received += len(message.get("body", b""))
        if received > length or received > MAX_BODY:
            raise MultiPartException("Request too large")
        return message

    request._receive = limited_receive
    try:
        return await call_next(request)
    finally:
        job_lock.release()


async def run_worker(mode, path, language):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(WORKER), mode, path, language or "",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(JOB_TIMEOUT):
            output, _ = await proc.communicate()
    except (TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode == 65:
        logger.error("Speech worker produced invalid SRT")
        raise HTTPException(422, "Speech worker produced invalid SRT")
    if proc.returncode != 0:
        logger.error("Speech worker failed with exit code %s", proc.returncode)
        raise HTTPException(500, "Speech worker failed")
    if not output.strip():
        raise HTTPException(422, "No speech output")
    return output


async def process(request, mode, language=None):
    if request.query_params.get("encode") != "false":
        raise HTTPException(400, "Only encode=false raw PCM is supported")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "multipart/form-data":
        raise HTTPException(415, "Multipart upload required")
    try:
        async with asyncio.timeout(UPLOAD_TIMEOUT):
            form = await request.form(max_files=1, max_fields=4, max_part_size=16384)
    except TimeoutError:
        raise HTTPException(408, "Upload timed out")
    try:
        files = form.getlist("audio_file")
        if len(files) != 1 or not isinstance(files[0], UploadFile):
            raise HTTPException(400, "One audio_file upload is required")
        audio = files[0]
        if audio.size is None or audio.size == 0 or audio.size % 2:
            raise HTTPException(400, "Expected nonempty 16-bit PCM")
        if audio.size > MAX_AUDIO:
            raise HTTPException(413, "Audio exceeds two hours")
        with tempfile.TemporaryDirectory(prefix="speech-") as directory:
            path = os.path.join(directory, "audio.pcm")
            with open(path, "xb") as target:
                while chunk := await audio.read(1024 * 1024):
                    target.write(chunk)
            try:
                return await run_worker(mode, path, language)
            except TimeoutError:
                logger.error("Speech worker timed out")
                raise HTTPException(504, "Speech worker timed out")
    finally:
        await form.close()


@app.post("/asr")
async def asr(request: Request):
    task = request.query_params.get("task", "transcribe")
    language = request.query_params.get("language")
    if task not in {"transcribe", "translate"}:
        raise HTTPException(400, "Unsupported task")
    if language is not None and language not in LANGUAGES:
        raise HTTPException(400, "Unsupported input language")
    if request.query_params.get("output") != "srt":
        raise HTTPException(400, "Only SRT output is supported")
    return Response(await process(request, task, language), media_type="text/plain")


@app.post("/detect-language")
async def detect_language(request: Request):
    return Response(await process(request, "detect"), media_type="application/json")
