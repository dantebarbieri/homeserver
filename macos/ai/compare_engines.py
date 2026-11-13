"""Private, sequential comparisons of the three explicitly selected episodes.

Run from the operator's machine with SSH aliases `server` and `ai-studio`.
`prepare --sources PRIVATE_MANIFEST_JSON` reads the private episode paths and
creates a new private directory on the Studio; `server KIND` or `studio KIND`
sends the exact retained PCM to that engine. No Bazarr settings or source
media are changed. Inspect load and coordinate other jobs first.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = "/Users/dante/Services/ai-staging/comparison-20261113"
KINDS = ("english", "japanese", "telugu")

# Executed inside the existing server container, not a second model process.
# HTTP error bodies are preserved as diagnostic artifacts, never subtitle success.
CLIENT = r'''
import hashlib, json, sys, time, urllib.error, urllib.request, uuid
raw = sys.stdin.buffer.read()
boundary = uuid.uuid4().hex
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="audio_file"; '
        'filename="comparison.pcm"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
request = urllib.request.Request(
    sys.argv[1], data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
started = time.monotonic()
try:
    response = urllib.request.urlopen(request, timeout=1200)
except urllib.error.HTTPError as error:
    response = error
with response:
    result = response.read()
    status = response.status
sys.stdout.buffer.write(result)
print(json.dumps({"status": status, "seconds": time.monotonic() - started,
                  "pcm_sha256": hashlib.sha256(raw).hexdigest(),
                  "response_sha256": hashlib.sha256(result).hexdigest(),
                  "response_bytes": len(result)}), file=sys.stderr)
'''


def ssh(host, command, **kwargs):
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, command], check=True, **kwargs
    )


def capture(host, command):
    return ssh(host, command, stdout=subprocess.PIPE).stdout


def save(name, data, root=ROOT):
    # noclobber protects all previous comparison outputs, including failures.
    command = f"umask 077; set -C; cat > {shlex.quote(root + '/' + name)}"
    ssh("ai-studio", command, input=data)


def transfer(command, name):
    source = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "server", command], stdout=subprocess.PIPE
    )
    destination = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", "ai-studio",
         f"umask 077; set -C; cat > {shlex.quote(ROOT + '/' + name)}"],
        stdin=subprocess.PIPE,
    )
    digest, size = hashlib.sha256(), 0
    try:
        while chunk := source.stdout.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            destination.stdin.write(chunk)
    finally:
        source.stdout.close()
        destination.stdin.close()
    source_code = source.wait()
    destination_code = destination.wait()
    if source_code or destination_code:
        raise RuntimeError(f"Transfer failed: source={source_code}, destination={destination_code}")
    return {"sha256": digest.hexdigest(), "bytes": size}


def prepare(sources_path):
    sources = json.loads(sources_path.read_text(encoding="utf-8"))["episodes"]
    if set(sources) != set(KINDS):
        raise ValueError("Source manifest must contain english, japanese and telugu episodes")
    ssh("ai-studio", f"umask 077; mkdir {shlex.quote(ROOT)}")
    manifest = {"pcm_format": "s16le mono 16000Hz", "episodes": {}}
    for kind, source in sources.items():
        path = shlex.quote(source["path"])
        probe = json.loads(capture("server",
            f"docker exec bazarr ffprobe -v error -show_format -show_streams -of json {path}"))
        audio = next(s for s in probe["streams"] if s["index"] == source["audio_stream"])
        expected = {"english": "eng", "japanese": "jpn", "telugu": "tel"}[kind]
        if audio.get("tags", {}).get("language") != expected:
            raise RuntimeError(f"Unexpected {kind} audio language")
        command = (
            f"docker exec bazarr ffmpeg -nostdin -v error -threads 1 -i {path} "
            f"-map 0:{source['audio_stream']} -vn -ac 1 -ar 16000 -f s16le pipe:1"
        )
        pcm = transfer(command, f"{kind}.pcm")
        if not pcm["bytes"] or pcm["bytes"] % 2:
            raise RuntimeError("Invalid PCM byte count")
        if kind == "telugu":
            reference = f"docker exec bazarr cat {shlex.quote(source['path'][:-4] + '.en.ass')}"
        else:
            reference = (
                f"docker exec bazarr ffmpeg -nostdin -v error -i {path} "
                f"-map 0:{source['reference_stream']} -c:s copy "
                f"-f {source['reference_format']} pipe:1"
            )
        ref = transfer(reference, f"{kind}-reference.{source['reference_format']}")
        manifest["episodes"][kind] = {
            **source, "probe": probe, "pcm": pcm, "reference": ref,
            "extraction_command": command,
        }
        save(f"{kind}-source.json", json.dumps(manifest["episodes"][kind], indent=2).encode())
        print(f"{kind}: {pcm['bytes']} PCM bytes, sha256={pcm['sha256']}", flush=True)
    save("manifest.json", json.dumps(manifest, indent=2).encode())


def runtime():
    code = """
import hashlib, inspect, importlib.metadata as m, json
from pathlib import Path
from faster_whisper import WhisperModel
from app.config import CONFIG
files = ['/app/app/asr_models/faster_whisper_engine.py', '/app/app/webservice.py']
print(json.dumps({
    'packages': {n:m.version(n) for n in
                 ['faster-whisper','ctranslate2','whisper-asr-webservice']},
    'settings': {n:getattr(CONFIG,n) for n in
                 ['ASR_ENGINE','MODEL_NAME','DEVICE','MODEL_QUANTIZATION','MODEL_PATH']},
    'signature': str(inspect.signature(WhisperModel.transcribe)),
    'source_sha256': {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files},
    'snapshots': [str(p) for p in Path(CONFIG.MODEL_PATH).glob('*/snapshots/*')],
}))
"""
    data = json.loads(capture("server",
        "docker exec whisperasr /app/.venv/bin/python -c " + shlex.quote(code)))
    data["container_image"] = capture("server",
        "docker inspect whisperasr --format '{{.Image}}'").decode().strip()
    data["host_load"] = capture("server", "uptime").decode().strip()
    data["gpu"] = capture("server",
        "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total "
        "--format=csv,noheader").decode().strip()
    save("server-runtime.json", json.dumps(data, indent=2).encode())
    print("Server runtime metadata retained")


def run_engine(engine, kind, output_root=ROOT):
    prefix = shlex.quote(output_root + "/" + kind + "-" + engine)
    ssh("ai-studio",
        f"test -d {shlex.quote(output_root)} && test -w {shlex.quote(output_root)}"
        f" && test ! -e {prefix}.srt && test ! -e {prefix}.error && test ! -e {prefix}.json")
    manifest = json.loads(capture("ai-studio", f"cat {shlex.quote(ROOT + '/manifest.json')}"))
    source = manifest["episodes"][kind]
    query = (f"/asr?task={source['task']}&language={source['language']}"
             "&output=srt&encode=false")
    raw = capture("ai-studio", f"cat {shlex.quote(ROOT + '/' + kind + '.pcm')}")
    if (len(raw) != source["pcm"]["bytes"] or len(raw) > 230400000
            or hashlib.sha256(raw).hexdigest() != source["pcm"]["sha256"]):
        raise RuntimeError("PCM checksum changed")
    if engine == "server":
        command = ("docker exec -i whisperasr /app/.venv/bin/python -c "
                   + shlex.quote(CLIENT) + " " + shlex.quote("http://127.0.0.1:9000" + query))
        host = "server"
    else:
        command = ("uv run --no-project python -c " + shlex.quote(CLIENT) + " "
                   + shlex.quote("http://127.0.0.1:9000" + query))
        host = "ai-studio"
    result = ssh(host, command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    metadata = json.loads(result.stderr.decode().strip())
    if metadata["pcm_sha256"] != source["pcm"]["sha256"]:
        raise RuntimeError("Engine received different PCM")
    suffix = "srt" if metadata["status"] == 200 else "error"
    save(f"{kind}-{engine}.{suffix}", result.stdout, root=output_root)
    metadata.update({"engine": engine, "kind": kind, "query": query})
    save(f"{kind}-{engine}.json", json.dumps(metadata, indent=2).encode(), root=output_root)
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "runtime", "server", "studio"))
    parser.add_argument("kind", nargs="?", choices=KINDS)
    parser.add_argument("--sources", type=Path,
                        help="Private JSON manifest containing the episodes and source paths")
    parser.add_argument("--output-directory", default=ROOT,
                        help="Existing private Studio directory for new endpoint outputs")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.sources is None:
            parser.error("prepare requires --sources PRIVATE_MANIFEST_JSON")
        prepare(args.sources)
    elif args.action == "runtime":
        runtime()
    elif args.kind is None:
        parser.error("Engine comparison needs one episode kind")
    else:
        run_engine(args.action, args.kind, args.output_directory)
