"""Re-run a benchmark clip with Whisper's previous-text conditioning disabled.

Usage (as _studio, in the worker's ai/ environment):
    condition_false.py english|japanese|telugu
Produces the *-condition-false.srt results cited in SPEECH.md.
"""
import time
import sys
from pathlib import Path

import mlx_whisper
import numpy as np
from huggingface_hub import snapshot_download
from mlx_whisper.writers import WriteSRT

base = Path("/var/lib/studio-worker/ai-tests/benchmark-20261113")
kind = sys.argv[1]
language, task = {"english": ("en", "transcribe"), "japanese": ("ja", "translate"),
                  "telugu": ("te", "translate")}[kind]
audio = np.fromfile(base / f"{kind}.pcm", dtype="<i2").astype(np.float32) / 32768
model = snapshot_download(
    "mlx-community/whisper-large-v3-mlx",
    revision="49e6aa286ad60c14352c404340ded53710378a11",
    local_files_only=True,
)
started = time.monotonic()
result = mlx_whisper.transcribe(
    audio, path_or_hf_repo=model, task=task, language=language,
    condition_on_previous_text=False, verbose=None,
)
with (base / f"{kind}-condition-false.srt").open("x", encoding="utf-8") as output:
    WriteSRT(".").write_result(result, output)
print(f"Completed in {time.monotonic() - started:.1f} seconds")
