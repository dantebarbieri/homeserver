"""Short-lived, fixed-model inference worker for whisper_adapter."""

import io
import json
import re
import sys

import numpy as np

MODEL = "mlx-community/whisper-large-v3-mlx"
REVISION = "49e6aa286ad60c14352c404340ded53710378a11"
TIMING = re.compile(
    r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3}) --> "
    r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})"
)


def read_pcm(path, samples=-1):
    return np.fromfile(path, dtype="<i2", count=samples).astype(np.float32) / 32768.0


def decoding_options(mode, language):
    if mode == "transcribe" and language == "en":
        return {"condition_on_previous_text": False}
    return {}


def validate_srt(text):
    previous_start = -1
    for index, block in enumerate(re.split(r"\n\s*\n", text.strip()), 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(index) or not any(line.strip() for line in lines[2:]):
            raise ValueError("Invalid SRT cue")
        match = TIMING.fullmatch(lines[1])
        if match is None:
            raise ValueError("Invalid SRT timestamp")
        values = [int(value) for value in match.groups()]
        start = ((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 + values[3]
        end = ((values[4] * 60 + values[5]) * 60 + values[6]) * 1000 + values[7]
        if end <= start or start < previous_start:
            raise ValueError("Invalid SRT timing")
        previous_start = start


def main():
    import mlx.core as mx
    import mlx_whisper
    from huggingface_hub import snapshot_download
    from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.tokenizer import LANGUAGES
    from mlx_whisper.transcribe import ModelHolder
    from mlx_whisper.writers import WriteSRT

    mode, path, language = sys.argv[1:]
    model_path = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    if mode == "detect":
        audio = mx.array(read_pcm(path, N_SAMPLES))
        model = ModelHolder.get_model(model_path, mx.float16)
        mel = log_mel_spectrogram(pad_or_trim(audio), n_mels=model.dims.n_mels)
        segment = pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16)
        _, probabilities = model.detect_language(segment)
        code = max(probabilities, key=probabilities.get)
        print(json.dumps({
            "language_code": code,
            "detected_language": LANGUAGES[code],
            "confidence": float(probabilities[code]),
        }))
    else:
        audio = read_pcm(path)
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=model_path, task=mode,
            language=language or None, verbose=None, **decoding_options(mode, language),
        )
        output = io.StringIO()
        WriteSRT(".").write_result(result, output)
        text = output.getvalue()
        if text.strip():
            try:
                validate_srt(text)
            except ValueError:
                raise SystemExit(65)
        print(text, end="")


if __name__ == "__main__":
    main()
