"""Isolated diagnostic capture of raw MLX output, including invalid SRT.

Run only as the speech service account, on a private test copy of audio, while
the API is idle. This does not change the service or return unchecked text to
Bazarr. The normal API continues to reject invalid timing. Output files must
not already exist. Diagnostic text can still contain omissions/hallucinations.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np


MODEL = "mlx-community/whisper-large-v3-mlx"
REVISION = "49e6aa286ad60c14352c404340ded53710378a11"


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcm", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", required=True, choices=("en", "ja", "te"))
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        parser.error("Output already exists")

    import mlx_whisper
    from huggingface_hub import snapshot_download
    from mlx_whisper.writers import WriteSRT

    raw = args.pcm.read_bytes()
    if not raw or len(raw) % 2 or len(raw) > 230400000:
        parser.error("Invalid or oversized PCM")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    model_path = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    task = "transcribe" if args.language == "en" else "translate"
    options = {"condition_on_previous_text": False} if args.language == "en" else {}
    started = time.monotonic()
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model_path, task=task,
        language=args.language, verbose=None, **options,
    )
    output = io.StringIO()
    WriteSRT(".").write_result(result, output)
    text = output.getvalue()
    metadata = {
        "seconds": time.monotonic() - started,
        "pcm_sha256": hashlib.sha256(raw).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "model": MODEL, "revision": REVISION, "task": task,
        "language": args.language, "decoder_overrides": options,
        "diagnostic_raw_capture": True,
    }
    with args.output.open("x", encoding="utf-8") as target:
        target.write(text)
    with args.output.with_suffix(".json").open("x", encoding="utf-8") as target:
        json.dump(metadata, target, indent=2)
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
