# Speech model evaluation

The target is Telugu/Indian-language mythological film, Japanese anime and
English, including English subtitles with reliable timing. Do not select a
model based on size, a clean-English leaderboard or the server's settings.
No Mac-to-Bazarr cutover has been made.

Large-v3 was initially chosen because it was already available, supports both
target languages and direct translation, and had an MLX CLI that could be
tested immediately. That established a baseline; it did not establish the
best Mac model or justify copying the server's settings.

## Provisional routing

* **Telugu to English subtitles:** retain MLX Whisper large-v3 only as the
  working timing/transcription baseline while evaluating alternatives.
  Its translation is not reliably English: on one clean synthetic Telugu
  greeting it produced a transliteration instead. SeamlessM4T v2 translated
  that greeting correctly in an initial local test, so it is the leading
  **candidate to evaluate**, not a proven default. Compare it with Telugu ASR
  plus a Telugu-capable text translator on actual film clips. Neither route
  has been validated for this workload or integrated into a subtitle pipeline.
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

## Candidates and constraints

| Model | Scope | Practical considerations |
| --- | --- | --- |
| [Whisper large-v3](https://github.com/openai/whisper) | Multilingual ASR, language detection, and direct speech-to-English translation; includes Telugu and Japanese. | MLX CLI and SRT work locally. Translation quality varies by language; the Telugu result above demonstrates a failure. Timestamps are model predictions, not verified ground truth. |
| [Whisper large-v3-turbo](https://github.com/openai/whisper#command-line-usage) | Faster multilingual transcription. | OpenAI explicitly says turbo was **not trained for translation** and may return the source language even when asked to translate. Not a replacement for direct translation. |
| [Qwen3-ASR 1.7B and aligner](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | ASR: 30 languages including Hindi, Japanese and English, **not Telugu**. Forced alignment: 11 languages including Japanese and English, **not Telugu**. | [MLX implementation](https://github.com/moona3k/mlx-qwen3-asr) supports SRT; its documented 1.7B fp16 estimate is ~3.4 GB plus the aligner and runtime. It does not directly translate speech. |
| [SeamlessM4T v2 large](https://github.com/facebookresearch/seamless_communication/blob/main/docs/m4t/README.md#supported-languages) | Telugu and Japanese speech input and English text output, including direct speech-to-text translation. | 2.3B parameters; published model is [CC BY-NC 4.0](https://huggingface.co/facebook/seamless-m4t-v2-large), unlike MIT Whisper. PyTorch MPS ran a short test with CPU fallback enabled; full GPU coverage, memory, long-form segmentation, timing, and real-media quality are not established. Direct output is text, not a finished timestamped SRT. |
| [Omnilingual ASR](https://huggingface.co/facebook/omniASR-LLM-7B) | ASR includes `tel_Telu`, `jpn_Jpan` and `eng_Latn`; not a speech-translation model. | The LLM 7B card gives ~17 GiB inference memory for 30 seconds in BF16 on an **A100**, not a Mac measurement, and 30 GiB FP32 download. It is a poor first coexistence choice beside 6 GB Colima and other work; Apple acceleration and subtitle alignment remain unverified. |
| [AI4Bharat IndicConformer Telugu](https://huggingface.co/ai4bharat/indicconformer_stt_te_hybrid_ctc_rnnt_large) | Telugu ASR only; 120M-parameter encoder, not translation. | Specialized comparison candidate, but its documented NeMo path does not establish Apple GPU, subtitle timing or NTR-film accuracy. |
| [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Transcription and word timestamps for 25 European languages including English. | Does not list Telugu or Japanese, and does not provide direct speech translation. |

Unified memory is shared by the OS, GPU, Colima, LLM and video workers. Model
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
  established whether that setting is preferable for other languages.
* Japanese-to-English translation took 104 seconds for a 22m51s anime episode.
  Dialogue-only reference cues overlapped most generated cues, but overlap
  does not establish translation correctness or exclude hallucinations.
* Telugu-to-English translation took 196 seconds for a 46m36s episode. Its
  SRT contained two reversed-duration cues, one backward start time, and
  repeated identical cues. The adapter now rejects invalid SRT timing rather
  than returning it as a successful subtitle.

The reference subtitles are not guaranteed verbatim transcripts; their timing
and phrasing can differ legitimately from speech. A fluent human needs to
review the content, including names, omissions and hallucinations. Do not
enable production subtitle generation based on timing overlap or API success.

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
