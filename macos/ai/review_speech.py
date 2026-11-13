"""Local subtitle evidence for the controlled Whisper comparison.

Metrics are diagnostics, not semantic quality scores. `windows` prints private
reference/output text for agent review; do not commit that output. Translation
references can legitimately use different words and segmentation.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics


def seconds(text):
    hours, minutes, value = text.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(value)


def clean(text):
    return " ".join(re.sub(r"\{[^}]*\}|<[^>]*>", "", text)
                    .replace(r"\N", " ").replace(r"\n", " ").split())


def read_cues(path):
    text = path.read_text(encoding="utf-8-sig")
    cues = []
    if path.suffix == ".ass":
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) != 10:
                    raise ValueError("Malformed ASS dialogue")
                if parts[3] in {"Default", "DefaultTop"}:
                    cues.append((seconds(parts[1]), seconds(parts[2]), clean(parts[9])))
        return sorted(cues)
    if not text.strip():
        raise ValueError("Empty subtitle file")
    for index, block in enumerate(re.split(r"\n\s*\n", text.strip()), 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(index) or "-->" not in lines[1]:
            raise ValueError(f"Malformed SRT cue {index}")
        start, end = lines[1].split("-->")
        cues.append((seconds(start.strip()), seconds(end.strip()), clean(" ".join(lines[2:]))))
    return cues


def words(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text.casefold(), re.UNICODE)


def metric(reference, actual, audio_duration=None):
    word_reference = [cue for cue in reference if words(cue[2])]
    word_actual = [cue for cue in actual if words(cue[2])]
    overlap = lambda a, b: min(a[1], b[1]) > max(a[0], b[0])
    durations = [end - start for start, end, _ in actual]
    cps = [len(text) / (end - start) for start, end, text in actual if end > start]
    start_errors = []
    for ref in word_reference:
        candidates = [cue for cue in word_actual if overlap(ref, cue)]
        if candidates:
            start_errors.append(min(abs(cue[0] - ref[0]) for cue in candidates))
    repeated = Counter(text.casefold() for _, _, text in actual)
    return {
        "cues": len(actual),
        "reference_word_cues": len(word_reference),
        "reference_word_cues_with_word_overlap": sum(
            any(overlap(ref, cue) for cue in word_actual) for ref in word_reference),
        "no_reference_overlap": sum(
            not any(overlap(ref, cue) for ref in reference) for cue in actual),
        "invalid_duration": sum(d <= 0 for d in durations),
        "negative_start": sum(start < 0 for start, _, _ in actual),
        "backward_start": sum(actual[i][0] < actual[i - 1][0] for i in range(1, len(actual))),
        "max_end_seconds": max(end for _, end, _ in actual),
        "cues_past_audio_end": sum(end > audio_duration + 0.1 for _, end, _ in actual)
            if audio_duration is not None else None,
        "nonword_cues": len(actual) - len(word_actual),
        "max_identical_cue_count": max(repeated.values()),
        "median_nearest_overlapping_start_delta_seconds": statistics.median(start_errors)
            if start_errors else None,
        "cues_under_0_5_seconds": sum(0 < d < 0.5 for d in durations),
        "cues_over_7_seconds": sum(d > 7 for d in durations),
        "cues_over_25_characters_per_second": sum(value > 25 for value in cps),
        "cues_over_84_characters": sum(len(text) > 84 for _, _, text in actual),
        "words": sum(len(words(text)) for _, _, text in actual),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("kind", choices=("english", "japanese", "telugu"))
    parser.add_argument("--windows", action="store_true")
    parser.add_argument("--engine", choices=("studio", "server", "all"), default="all")
    parser.add_argument("--studio-file", type=Path,
                        help="Studio API SRT from a separate comparison run")
    parser.add_argument("--raw-studio", type=Path,
                        help="Separately labelled diagnostic rerun, not a successful API result")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=3600)
    parser.add_argument("--step", type=int, default=120)
    args = parser.parse_args()
    root, kind = args.directory, args.kind
    if args.studio_file is not None and not args.studio_file.is_file():
        parser.error("Studio API subtitle file does not exist")
    extension = "srt" if kind == "english" else "ass"
    reference = read_cues(root / f"{kind}-reference.{extension}")
    files = {"reference": reference}
    for engine in ("studio", "server"):
        if args.engine not in {engine, "all"}:
            continue
        path = (args.studio_file if engine == "studio" and args.studio_file is not None
                else root / f"{kind}-{engine}.srt")
        if path.exists():
            files[engine] = read_cues(path)
    if args.raw_studio is not None:
        files["studio_raw_diagnostic"] = read_cues(args.raw_studio)
    if args.windows:
        for start in range(args.start, args.end, args.step):
            print(f"\n[{start // 60:02d}:{start % 60:02d}-"
                  f"{(start + args.step) // 60:02d}:{(start + args.step) % 60:02d}]")
            for label, cues in files.items():
                texts = [text for a, b, text in cues if start <= (a + b) / 2 < start + args.step]
                print(label + ": " + " ".join(texts))
    else:
        duration = json.loads((root / "manifest.json").read_text())["episodes"][kind]["pcm"]["bytes"] / 32000
        print(json.dumps({label: metric(reference, cues, duration) for label, cues in files.items()
                          if label != "reference"}, indent=2))


if __name__ == "__main__":
    main()
