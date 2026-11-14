"""Timing-overlap metrics for generated subtitles against reference subtitles.

Usage: compare_speech.py DIR KIND [OUTPUT [OFFSET [DURATION]]]

DIR holds KIND-whisper.srt (or OUTPUT) and the reference: english-reference.srt
for KIND=english, otherwise KIND-reference.ass (Default/DefaultTop styles).
These numbers measure timing coverage and repetition, not transcript accuracy.
"""

import re
import statistics
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


def seconds(value):
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean(text):
    text = re.sub(r"\{[^}]*\}|<[^>]*>", "", text)
    text = text.replace(r"\N", " ").replace(r"\n", " ")
    return " ".join(text.split())


def srt(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    pattern = r"(?ms)^\s*\d+\s*\n(\d+:\d\d:\d\d,\d+)\s*-->\s*(\d+:\d\d:\d\d,\d+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)"
    return [(seconds(a), seconds(b), clean(c)) for a, b, c in re.findall(pattern, text)]


def ass(path, styles):
    events = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) == 10 and parts[3] in styles:
            events.append((seconds(parts[1]), seconds(parts[2]), clean(parts[9])))
    return sorted(events)


def words(text):
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text.lower(), re.UNICODE)


def main(root, kind, output=None, offset=0, duration=None):
    root = Path(root)
    actual = [(a + offset, b + offset, text) for a, b, text in
              srt(root / (output or f"{kind}-whisper.srt"))]
    if kind == "english":
        reference = srt(root / "english-reference.srt")
    else:
        reference = ass(root / f"{kind}-reference.ass", {"Default", "DefaultTop"})
    if duration is not None:
        reference = [cue for cue in reference if offset <= (cue[0] + cue[1]) / 2 < offset + duration]
    actual = [cue for cue in actual if cue[2]]
    reference = [cue for cue in reference if cue[2]]
    if not actual or not reference:
        raise ValueError("No readable subtitle cues")
    bad = sum(end <= start or start < 0 for start, end, _ in actual)
    nonmonotonic = sum(actual[i][0] < actual[i - 1][0] for i in range(1, len(actual)))
    overlapping_refs = 0
    pair_scores = []
    deltas = []
    for start, end, text in reference:
        matches = [cue for cue in actual if min(end, cue[1]) - max(start, cue[0]) > 0]
        if not matches:
            continue
        overlapping_refs += 1
        best = min(matches, key=lambda x: abs(x[0] - start))
        deltas.append(abs(best[0] - start))
        pair_scores.append(SequenceMatcher(None, words(text), words(" ".join(m[2] for m in matches))).ratio())
    unmatched_generated = sum(
        not any(min(end, ref[1]) - max(start, ref[0]) > 0 for ref in reference)
        for start, end, _ in actual
    )
    word_reference = [cue for cue in reference if words(cue[2])]
    word_actual = [cue for cue in actual if words(cue[2])]
    word_overlap = sum(
        any(min(end, cue[1]) - max(start, cue[0]) > 0 for cue in word_actual)
        for start, end, _ in word_reference
    )
    repetitions = Counter(cue[2].casefold() for cue in actual)
    all_words = words(" ".join(cue[2] for cue in actual))
    print(f"{kind}: generated={len(actual)}, reference={len(reference)}, invalid={bad}, nonmonotonic={nonmonotonic}")
    print(f"reference cues with temporal overlap={overlapping_refs}/{len(reference)}; generated cues without reference overlap={unmatched_generated}/{len(actual)}")
    print(f"word-bearing reference cues with word-bearing generated overlap={word_overlap}/{len(word_reference)}; non-word generated cues={len(actual)-len(word_actual)}/{len(actual)}")
    print(f"median nearest overlapping cue-start difference={statistics.median(deltas):.2f}s; median aligned token similarity={statistics.median(pair_scores):.3f}")
    print(f"most-repeated identical generated cue count={max(repetitions.values())}; generated tokens={len(all_words)}; non-ASCII-letter token fraction={sum(any(ord(c)>127 for c in w) for w in all_words)/max(len(all_words),1):.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None,
         float(sys.argv[4]) if len(sys.argv) > 4 else 0,
         float(sys.argv[5]) if len(sys.argv) > 5 else None)
