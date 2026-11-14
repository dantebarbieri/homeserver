"""Short-lived, fixed-model inference worker for whisper_adapter."""

import io
import json
import re
import sys

import numpy as np

MODEL = "mlx-community/whisper-large-v3-mlx"
REVISION = "49e6aa286ad60c14352c404340ded53710378a11"
# Telugu reproduces the server's whisper-asr-webservice faster_whisper engine
# (beam search, which mlx-whisper lacks) on the CPU, at float32 rather than CUDA float16.
FASTER_WHISPER_MODEL = "Systran/faster-whisper-large-v3"
FASTER_WHISPER_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478"
FASTER_WHISPER_LANGUAGES = frozenset({"te"})
FASTER_WHISPER_THREADS = 12
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


def uses_faster_whisper(mode, language):
    return mode in {"transcribe", "translate"} and language in FASTER_WHISPER_LANGUAGES


def srt_timestamp(milliseconds):
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def segments_to_srt(segments):
    """Format segments like the webservice's SRT writer, omitting cues without text."""
    cues = []
    for segment in segments:
        text = segment.text.strip().replace("-->", "->")
        if text:
            cues.append(
                f"{len(cues) + 1}\n{srt_timestamp(round(segment.start * 1000))} --> "
                f"{srt_timestamp(round(segment.end * 1000))}\n{text}\n"
            )
    return "\n".join(cues)


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


def repair_srt(text, duration_ms):
    """Repair bounded timestamp defects without dropping or inventing text."""
    cues = []
    latest_start = 0
    counts = {"reordered": 0, "invalid_duration": 0, "overlap": 0, "shifted": 0}
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
        if start >= duration_ms or end > duration_ms + 1000:
            raise ValueError("SRT timing outside audio")
        if latest_start - start > 30000 or start - end > 30000:
            raise ValueError("SRT timing anomaly exceeds repair limit")
        if start < latest_start:
            counts["reordered"] += 1
        latest_start = max(start, latest_start)
        if end <= start:
            counts["invalid_duration"] += 1
        cues.append((start, end, lines[2:]))
    if not cues:
        raise ValueError("Empty SRT")
    cues.sort(key=lambda cue: cue[0])
    output = []
    previous_start = -1
    adjusted = []
    for start, end, lines in cues:
        adjusted_start = start if start > previous_start else previous_start + 100
        if adjusted_start - start > 2000:
            raise ValueError("SRT cues too dense to repair")
        if adjusted_start != start:
            counts["shifted"] += 1
        adjusted.append((adjusted_start, end, lines))
        previous_start = adjusted_start
    for i, (adjusted_start, end, lines) in enumerate(adjusted):
        limit = adjusted[i + 1][0] if i + 1 < len(adjusted) else duration_ms
        limit = min(limit, duration_ms)
        if limit <= adjusted_start:
            raise ValueError("SRT cues too dense to repair")
        if end <= adjusted_start:
            end = min(adjusted_start + 2000, limit)
        elif end > limit:
            end = limit
            counts["overlap"] += 1
        if end <= adjusted_start:
            raise ValueError("SRT cue too short to repair")
        output.append(f"{i + 1}\n{srt_timestamp(adjusted_start)} --> {srt_timestamp(end)}\n"
                      + "\n".join(lines))
    result = "\n\n".join(output) + "\n"
    validate_srt(result)
    return result, counts


def detect_mlx(path):
    import mlx.core as mx
    from huggingface_hub import snapshot_download
    from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.tokenizer import LANGUAGES
    from mlx_whisper.transcribe import ModelHolder

    model_path = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    audio = mx.array(read_pcm(path, N_SAMPLES))
    model = ModelHolder.get_model(model_path, mx.float16)
    mel = log_mel_spectrogram(pad_or_trim(audio), n_mels=model.dims.n_mels)
    segment = pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16)
    _, probabilities = model.detect_language(segment)
    code = max(probabilities, key=probabilities.get)
    return {
        "language_code": code,
        "detected_language": LANGUAGES[code],
        "confidence": float(probabilities[code]),
    }


def transcribe_mlx(audio, mode, language):
    import mlx_whisper
    from huggingface_hub import snapshot_download
    from mlx_whisper.writers import WriteSRT

    model_path = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model_path, task=mode,
        language=language or None, verbose=None, **decoding_options(mode, language),
    )
    output = io.StringIO()
    WriteSRT(".").write_result(result, output)
    return output.getvalue()


def transcribe_faster_whisper(audio, mode, language):
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download

    model_path = snapshot_download(
        FASTER_WHISPER_MODEL, revision=FASTER_WHISPER_REVISION, local_files_only=True
    )
    model = WhisperModel(
        model_path, device="cpu", compute_type="float32", cpu_threads=FASTER_WHISPER_THREADS
    )
    segments, _ = model.transcribe(audio, beam_size=5, task=mode, language=language)
    return segments_to_srt(segments)


def main():
    mode, path, language = sys.argv[1:]
    if mode == "detect":
        print(json.dumps(detect_mlx(path)))
    else:
        audio = read_pcm(path)
        if uses_faster_whisper(mode, language):
            text = transcribe_faster_whisper(audio, mode, language)
        else:
            text = transcribe_mlx(audio, mode, language)
        if text.strip():
            try:
                text, counts = repair_srt(text, len(audio) * 1000 // 16000)
                if any(counts.values()):
                    print(f"SRT timing repair: {json.dumps(counts)}", file=sys.stderr)
            except ValueError as error:
                print(f"SRT timing rejected: {error}", file=sys.stderr)
                raise SystemExit(65)
        print(text, end="")


if __name__ == "__main__":
    main()
