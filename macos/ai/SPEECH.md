# Speech model evaluation

The target is Telugu/Indian-language mythological film, Japanese anime and
English, including English subtitles with reliable timing. Do not select a
model based on size, a clean-English leaderboard or the server's settings.
Dante decided on 2026-11-13 to move Bazarr's Whisper work to the Studio.
Bazarr now uses the authenticated Studio
[transport](README.md#bazarr-transport-and-cutover); the server's Whisper
service remains running for rollback.

**Installed:** MLX Whisper large-v3, with previous-text conditioning disabled
only for English transcription, except for Telugu input, which runs the
server's faster-whisper model on the CPU ([Telugu on the CPU](#telugu-on-the-cpu)).
Ollama's separate `qwen3:8b` model is for future text automations, not speech
recognition. Qwen3-ASR, its aligner and SeamlessM4T were comparisons, not
selected services; their benchmark installations have been removed.

The initial private benchmark subtitles remain on the Studio; their audio and
duplicate scripts were cleaned up with permission. The subsequent comparison
re-extracted audio into a separate private directory. See the
[retained inventory](../DECISIONS.md#on-the-studio) and the full-episode results below.

See the [same-input server-versus-Studio comparison](COMPARISON.md) for a
subsequent full-episode agent review of the words, endpoint failures and
practical per-language readiness, beyond timing-overlap statistics. A later
Studio-only Telugu rerun repaired the SRT timing but was materially more
repetitive than the server output; it did not meet the comparison gate. A
CPU run copying the server's decoding then tracked the server's output closely.

Large-v3 was initially chosen because it was already available, supports both
target languages and direct translation, and had an MLX CLI that could be
tested immediately. That established a baseline; it did not establish the
best Mac model or justify copying the server's settings.

## Provisional routing

* **Telugu to English subtitles:** faster-whisper large-v3 on the CPU, copying
  the server ([below](#telugu-on-the-cpu)). Its repetition and timing metrics
  are closer to the server's; comparable translation quality is not yet
  established, and the server itself is unreliable. SeamlessM4T v2
  translated a synthetic Telugu greeting correctly where MLX Whisper
  transliterated it, so it remains a **candidate to evaluate** for better
  translation, along with Telugu ASR plus a Telugu-capable text translator.
  Neither has been validated on film clips or integrated into a subtitle
  pipeline.
* **Japanese and English transcription:** evaluate Qwen3-ASR 1.7B plus its
  forced aligner in MLX against Whisper large-v3. Qwen's published ASR and
  aligner lists include Japanese and English, but not Telugu; it is a
  transcription model, not an English speech-translation model. Its native
  MLX implementation and Japanese tokenizer are separate third-party software.
  Keep Whisper as the Japanese-to-English baseline until translation quality
  and timing are compared on actual dialogue.
* **English speech-to-English subtitles:** compare Qwen ASR and Whisper
  transcription; translation is unnecessary. Parakeet v3 is another option for
  English transcription and timestamps, but its official 25-language list
  does not include Telugu or Japanese and it is not the common solution here.

## Telugu on the CPU

MLX Whisper's Telugu output repeated itself far more than the server's
([comparison](COMPARISON.md#telugu-timing-repair-rerun)), and MLX Whisper has
no beam search. The server's `whisperasr` runs faster-whisper 1.2.1 on
CTranslate2 4.8.1 with `Systran/faster-whisper-large-v3` revision `edaa852`,
beam size 5, in CUDA float16. CTranslate2 has no Apple GPU backend, so the
Studio runs the same versions, snapshot and decoding on 12 CPU threads in
float32. Only `language=te` requests use it.

On the same 2,789-second Vishnu Puran (2003) S01E01 audio as the comparison,
scored against the same 319-cue English reference:

| | Studio CPU, faster-whisper | Server GPU, faster-whisper | Studio MLX rerun |
| --- | --- | --- | --- |
| Inference time | 2,535 s (0.91× real time) | 344 s | 255 s |
| Cues | 547 | 528 | 708 |
| Reference word cues overlapped | 304 | 310 | 308 |
| Runs of 3+ identical cues | 7, longest 30 | 7, longest 30 | 23, longest 32 |
| Cues under 0.5 s | 0 | 1 | 15 |
| Cues over 25 characters/s | 51 | 44 | 85 |
| Word-sequence similarity to the server | 0.59 | — | 0.38 |
| Server cue texts reproduced exactly | 149 | — | 62 |

The CPU output needed no timing repair. It has the server's repetition
profile and similar coverage. It is not identical because CPU float32 and GPU
float16 arithmetic differ slightly, and decoding diverges after small
differences. The server's translation was already unreliable; nobody has
reviewed the CPU output's words beyond these statistics. A two-minute clip
through the deployed adapter returned 32 cues in 153 seconds, including model
loading.

The cost is speed: about real time, against about six minutes on the server
GPU. A three-hour film takes about three hours and blocks other Studio speech
jobs meanwhile, so the adapter gives Telugu jobs twice the audio's duration,
up to eight hours at the four-hour upload limit. int8 was roughly a third
faster in short probes, but its quality is untested; float32 is deployed.
Dante chose this route on 2026-11-13, accepting the slowdown and some Telugu
loss.

## Candidates and constraints

| Model | Scope | Practical considerations |
| --- | --- | --- |
| [Whisper large-v3](https://github.com/openai/whisper) | Multilingual ASR, language detection, and direct speech-to-English translation; includes Telugu and Japanese. | MLX CLI and SRT work locally. Translation quality varies by language; the Telugu result above demonstrates a failure. Timestamps are model predictions, not verified ground truth. |
| [Whisper large-v3-turbo](https://github.com/openai/whisper#command-line-usage) | Faster multilingual transcription. | OpenAI explicitly says turbo was **not trained for translation** and may return the source language even when asked to translate. Not a replacement for direct translation. |
| [Qwen3-ASR 1.7B and aligner](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | ASR: 30 languages including Hindi, Japanese and English, **not Telugu**. Forced alignment: 11 languages including Japanese and English, **not Telugu**. | [MLX implementation](https://github.com/moona3k/mlx-qwen3-asr) supports SRT; its documented 1.7B fp16 estimate is ~3.4 GB plus the aligner and runtime. It does not directly translate speech. |
| [SeamlessM4T v2 large](https://github.com/facebookresearch/seamless_communication/blob/main/docs/m4t/README.md#supported-languages) | Telugu and Japanese speech input and English text output, including direct speech-to-text translation. | 2.3B parameters; published model is [CC BY-NC 4.0](https://huggingface.co/facebook/seamless-m4t-v2-large), unlike MIT Whisper. PyTorch MPS ran a short test with CPU fallback enabled; full GPU coverage, memory, long-form segmentation, timing, and real-media quality are not established. Direct output is text, not a finished timestamped SRT. |
| [Omnilingual ASR](https://huggingface.co/facebook/omniASR-LLM-7B) | ASR includes `tel_Telu`, `jpn_Jpan` and `eng_Latn`; not a speech-translation model. | The LLM 7B card gives ~17 GiB inference memory for 30 seconds in BF16 on an **A100**, not a Mac measurement, and 30 GiB FP32 download. It is a poor first coexistence choice beside other work in 36 GB of unified memory; Apple acceleration and subtitle alignment remain unverified. |
| [AI4Bharat IndicConformer Telugu](https://huggingface.co/ai4bharat/indicconformer_stt_te_hybrid_ctc_rnnt_large) | Telugu ASR only; 120M-parameter encoder, not translation. | Specialized comparison candidate, but its documented NeMo path does not establish Apple GPU, subtitle timing or NTR-film accuracy. |
| [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Transcription and word timestamps for 25 European languages including English. | Does not list Telugu or Japanese, and does not provide direct speech translation. |

Unified memory is shared by the OS, GPU, LLM and video workers. Model
sizes are not hard process-memory ceilings, and no combined-load capacity
test has been run. Run one bounded speech job at a time; let the Ollama model
unload when it is not needed, and monitor memory pressure. Avoid installing
every candidate or loading several models merely because they fit on disk.

## What the initial checks prove

On the Studio, MLX Whisper 0.4.3 / large-v3 produced SRT from short synthetic
English speech and from synthetic Japanese and Telugu. On the Japanese
sample, transcription matched the supplied sentence and translation conveyed
its meaning. The Telugu transcript matched the greeting apart from punctuation,
but translation returned transliterated Telugu, not English. Spanish-to-English
also worked on a short synthetic sample. `mlx-qwen3-asr` 0.4.4 with Qwen3-ASR
1.7B and its aligner produced Japanese and English SRT matching the two short
synthetic sentences. SeamlessM4T v2 large translated the same synthetic Telugu
greeting as “Hello, today is a good day” but hallucinated an unrelated English
sentence for the Japanese greeting. It returned text only; no subtitle timing
was tested. These checks do not measure comparative accuracy, subtitle boundary
error, film dialogue, songs, noisy mixes, or long audio.

## Full-episode Whisper baseline

The `_studio` MLX large-v3 adapter was exercised on separate local copies of
three episodes against existing English subtitles. These are exploratory
comparisons, not a speaker-reviewed accuracy assessment:

* English transcription took 70 seconds for a 22m50s episode. A repeated
  punctuation-only output loop spanned roughly 98–288 seconds and overlapped
  about 90 word-bearing reference cues without word-bearing output. Processing
  the same 200-second section independently recovered speech in both the
  original mono mix and a separately extracted center-channel control. This
  makes long-form decoder state a concern; it does not prove a specific cause.
  A full-episode experiment with `condition_on_previous_text=False` eliminated
  the punctuation loop and improved word-bearing reference-cue overlap from
  527/630 to 623/630. It is not proof of semantic correctness, and has not
  established whether that setting is preferable for other languages. The
  experimental adapter applies it only to explicitly English transcription;
  a repeat through the installed service took 53 seconds, with 621/630
  word-bearing reference cues overlapping word-bearing output.
* Japanese-to-English translation took 104 seconds for a 22m51s anime episode.
  Dialogue-only reference cues overlapped most generated cues, but overlap
  does not establish translation correctness or exclude hallucinations.
  Disabling previous-text conditioning took 90.8 seconds and gave word-bearing
  overlap for 285/309 reference cues versus 304/309 with default conditioning,
  with different segmentation; this does not justify applying the English
  setting globally.
* Telugu-to-English translation took 196 seconds for a 46m36s episode. Its
  SRT contained two reversed-duration cues, one backward start time, and
  repeated identical cues. The adapter at that time rejected invalid SRT
  rather than returning it as a successful subtitle. Disabling previous-text
  conditioning eliminated the timestamp errors, but reduced word-bearing
  reference-cue overlap from 313/319 to 301/319 and left repeated output,
  including one cue repeated 45 times without reference overlap.

The reference subtitles are not guaranteed verbatim transcripts; their timing
and phrasing can differ legitimately from speech. A fluent human needs to
review the content, including names, omissions and hallucinations. Do not
enable production subtitle generation based on timing overlap or API success.
The overlap counts come from [`compare_speech.py`](compare_speech.py).

On the same English mono audio, the native Qwen3-ASR 1.7B plus forced aligner
produced word-bearing output overlapping 615/630 word-bearing reference cues,
without the Whisper punctuation loop, in 54.46 seconds. Its SRT had three
zero-duration cues, so it also requires timing validation before use. This
comparison does not establish which transcript is semantically more accurate.
Qwen does not provide Telugu ASR or direct speech-to-English translation.

## Before selecting a default

Use locally held, short, representative clips with trusted human transcripts,
English translations and timestamp references. Include multiple NTR Telugu
dialogue scenes with period diction, names, music and mixed languages, plus
Japanese anime dialogue and English speech. Compare models on the same clips:
transcription error (CER/WER with language-appropriate normalization),
translation adequacy and names reviewed by speakers, missing/hallucinated
speech, and start/end timing error. Check long-form chunk boundaries, drift,
overlap and subtitle readability as well as time, peak memory and pressure.
Do not treat existing translated subtitles as perfect transcripts or timestamp
ground truth.

For a two-stage route, preserve the original source-audio segment timings
through translation; do not pretend English translation words align directly
to Telugu or Japanese speech. Validate SRT syntax and review segmentation,
especially when the translation changes word order. Only promote a route after
the target-language tests justify it.
