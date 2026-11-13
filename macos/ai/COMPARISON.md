# Same-input Whisper comparison, 2026-11-13

**Practical assessment:** Studio English is a useful proofread fallback draft,
not a replacement for good human subtitles. Neither deployed stack is good
enough for unattended Japanese-to-English subtitles in this test. Studio's
Telugu API failed closed; the server returned readable SRT but materially
unreliable translation. Keep existing reference subtitles and do not cut over
Bazarr on this evidence.

## What was tested

These are the original episodes, not substituted clips:

| Episode | Selected audio | Reference |
| --- | --- | --- |
| Brooklyn Nine-Nine S01E01, Pilot; Netflix WEB-DL, DBTV | English, stream 1; 22m50s | Embedded English SRT, stream 4 |
| Parasyte -the maxim- S01E01, Metamorphosis; v2, MK-Pn8 | Japanese, stream 1; 22m51s | Full English ASS, stream 4, not signs-only stream 3 |
| Vishnu Puran (2003) S01E01, Episode 1; HDTV | Telugu, stream 3; 46m36s; **not default Hindi stream 1** | Matching English ASS sidecar identified by the user as the trusted series |

Audio was extracted read-only once as mono, 16 kHz, signed 16-bit
little-endian PCM. Both clients independently attested the SHA256 of the bytes
they submitted. The complete source paths, stream/format probes, extraction
commands, input/reference hashes, raw HTTP responses and per-request timing
metadata are retained in the private Studio directory
`~/Services/ai-staging/comparison-20261113`. Original media and subtitles were
not modified. No media or prompts were sent to third-party inference.

| Input | PCM bytes | SHA256 |
| --- | ---: | --- |
| English | 43844608 | `eeabccba144b7350046280dfae74db13a9155a3900eed99562eb5c63647b00c4` |
| Japanese | 43873280 | `ed72a0b743f976593b0fbaba95437b54593004f9aa6ef5fe2846c68cebead3c9` |
| Telugu | 89245696 | `726748fa9c971c4adf0967792c5e05f78bd7a9d7434c3b2385fe2f662c9a4435` |

## Deployed stacks, not a hardware-only experiment

Studio ran the isolated `_studio` loopback adapter with MLX Whisper 0.4.3,
MLX 0.32.4 and NumPy 2.5.4. A privileged read-only fingerprint independently
confirmed the installed adapter/worker hashes:

* adapter: `d4d868f73d0fa9f0e52e59d551235df90c8b6c8da382b4d64b89422bd71ed88e`
* worker: `2927120b6c99bde2cd8db01d7b5058569addf066884b74804c23d7ee09098fbf`

The worker requests the offline `mlx-community/whisper-large-v3-mlx` snapshot
`49e6aa286ad60c14352c404340ded53710378a11`. It uses MLX defaults except
`condition_on_previous_text=False` for explicit English transcription only.
Japanese/Telugu translation retains previous-text conditioning. Each request
loads a short-lived worker and validates SRT timing. The privileged read-only
lookup also confirmed that snapshot directory; the completed fingerprint is
retained as `studio-runtime.txt` in the private comparison directory.

The server ran the existing `whisperasr` API, not a second model process:
webservice 1.10.0, faster-whisper 1.2.1, CTranslate2 4.8.1, CUDA float16,
`Systran/faster-whisper-large-v3` snapshot
`edaa852ec7e145841d8ffdb056a99866b5f0a478`. Its deployed wrapper specifies
beam size 5; installed defaults retain previous-text conditioning and
temperature fallback. VAD and word timestamps were not enabled by these
requests. The image ID and source hashes are in `server-runtime.json`.

Thus both use the large-v3 family, but conversion, decoding, English context
handling and model residency differ. These were one run per deployed endpoint,
not controlled repeated measurements of GPU hardware or a model ranking.

## Measured endpoint results

| Task | Studio wall time / result | Server wall time / result |
| --- | --- | --- |
| English transcription | 54.8s, HTTP 200, 542 ordered positive-duration cues | 106.0s, HTTP 200, 621 ordered positive-duration cues |
| Japanese to English | 148.5s, HTTP 200, 499 ordered positive-duration cues | 184.2s, HTTP 200, 465 ordered positive-duration cues |
| Telugu to English | 276.8s, **HTTP 422: invalid SRT**; no successful subtitle | 343.8s, HTTP 200, 528 ordered positive-duration cues |

English word-bearing reference-cue overlap was 623/630 on Studio and 620/630
on the server; Japanese was 297/309 and 299/309; Telugu server was 310/319.
These high numbers are **not accuracy scores**: a wrong or invented sentence
can overlap a correct reference perfectly.

The English server output ended at 1397s, beyond the actual 1370.144s PCM
duration, with 14 cues extending beyond the audio. Studio English remained
within the input. The Japanese server output had one cue ending about 0.44s
past the input, a much smaller boundary defect. Both stacks can produce valid
SRT syntax without valid meaning.

Readability also differs. Studio/server English respectively had 59/38 cues
over 25 characters per second and 10/1 cues over 84 characters. These are
diagnostic thresholds, not a universal subtitle standard. Reference cues
and generated cues use different segmentation; timestamp overlap does not
establish audio alignment accuracy.

## Agent review of the words

The agent read the full English and Japanese reference/generated text in
successive two-minute windows, plus the full server Telugu/reference pair.
This was substantive text review, **not listening to the audio** and not a
fluent-speaker certification. The following are paraphrased findings, not raw
dialogue excerpts.

### English: usable draft, with corrections

Both largely preserve the investigation, captain conflict, bet and resolution.
Important negations in the opening and the final team/uniform explanation
remain understandable. Neither fresh run reproduced Studio's earlier
multi-minute punctuation-only loop.

Both confuse arrests with rest in the bet, and coroner with corner. Proper
names drift: Studio varies the suspect's name repeatedly during the chase;
the server also turns Santiago into a place name in one exchange. Studio
usually preserves more of the short dialogue: the server drops the captain's
brief introduction around 03m and several responses around 09m. Around
14-15m, both mangle the cheese/chase jokes; the server additionally loses
part of the theft-versus-murder reconstruction.

The server invents an extended apology/doctor-like exchange at the ending,
including timestamps after the audio has ended. Studio has smaller sign-off
recognition errors rather than that long invented ending. Conversely, the
server generally splits text into shorter, less rushed cues.

**Judgement:** Studio is preferable as a personal-viewing fallback draft for
this episode, subject to proofreading names, fast exchanges and timing.
Neither is an accessibility-quality or publication-ready replacement for
trusted human captions. This one episode does not establish a general pass.

**Reference limitation:** the embedded English track itself is fragmentary:
many cues omit part of a clause. Extracting it with subtitle decoding instead
of stream-copy produced identical bytes/hashes. Additional generated words
are therefore not automatically hallucinations; whole-reference WER would be
misleading. Agreement between the two engines also does not prove correctness.

### Japanese: neither is good enough unattended

Both recover recognizable everyday exchanges, the hand/brain explanation and
parts of the coexistence discussion, but also generate unrelated speech.
Studio repeats invented text across multiple stretches near 01-02m, 03-04m,
08-09m, 10-11m and 12m. The server has its own different loops and unrelated
dialogue, especially around 03-05m, 10m and 17-20m.

Meaning changes go beyond alternative translation wording. Around 13-14m,
the hospital/amputation explanation acquires an unrelated rabbit reference
in both outputs. Around 18-20m, a warning about the other creature's intention
to kill becomes guilt/worry in generated text, and the digestive-system
explanation becomes a fire-extinguisher reference. Around 20m, an observation
about lack of empathy becomes an anatomical phrase. Names, speaker agency and
conditional statements drift; invented names also appear in server text.

These are substantial contradictions or unsupported additions **against the
chosen reference**, not a claim that the agent independently verified Japanese
speech. Songs/signs were excluded from dialogue-reference metrics, so extra
song lyrics alone were not treated as hallucinations.

**Judgement:** neither stack is a defensible unattended anime-subtitle source
on this evidence. Existing full-dialogue ASS is strongly preferable. Studio
was faster here, not reliably better in meaning.

### Telugu: endpoint failure and unreliable server translation

Studio returned an explicit invalid-SRT error. No fresh Studio Telugu
transcript was returned to compare word-for-word. Its earlier retained raw
outputs are historical context, **not** a checksum-attested transcript from
this endpoint run. A separately labelled isolated diagnostic rerun needs
privileged access and scheduling; it must not replace the recorded HTTP 422.

The server's output often follows the broad creation-story sequence and gets
some lamp/perfection metaphors and later court discussion approximately
across. Nevertheless, its text contains major meaning failures against the
user-selected reference:

* Around 02-04m, the incarnations' actions are conflated, changing who saves
  whom rather than merely varying a deity's spelling.
* Around 18-20m, much of the explanation for creating Lakshmi is replaced by
  repetitive or unrelated statements.
* Around 22-24m, the sages' educational role becomes punishment/destruction,
  even though surrounding sentences still mention knowledge.
* Around 30-32m, a compliment about the voice changes polarity.
* Around 32-38m, the emergence of desire/hatred and the explanation of moral
  agency are partly reversed or replaced by repetitive assertions.
* Around 40-44m, mother/son/king relationships and who has the right to welcome
  the king are confused. Some later lines recover, but the error is material.

Chants and deity names may reasonably remain transliterated, dubs may differ,
and the reference can itself be imperfect. Those caveats do not justify
silently accepting changes to agency, negation, duties or family relations.

**Judgement:** no unattended Telugu-to-English approval for either stack.
The server returning HTTP 200 is not a quality pass; Studio's fail-closed
behaviour is safer than saving invalid SRT but does not solve translation.

## Operational limits and reproduction

Studio inference was scheduled while its Tdarr worker was inactive. Server
speech ran one request at a time after the Studio API jobs ended. Before
server inference, GPU utilisation sampled 0%, but Tdarr was using roughly
12 CPU cores on a 32-CPU server: **the homeserver was not idle**. During speech,
the GPU sampled roughly 88-90% utilisation and Whisper about one CPU core.
This comparison can raise fans; model inference is real GPU work.

All six endpoint attempts finished. A later user fan concern/SSH reservation
paused further SSH and diagnostic work; no additional jobs were started.
No production service was restarted or reconfigured, and no queued Bazarr
subtitle work was submitted.

`compare_engines.py` extracts inputs and records endpoint outcomes without
overwriting old files. `prepare --sources PRIVATE_MANIFEST_JSON` reads the
private manifest's `episodes` mapping, including each source `path`,
`audio_stream`, `language`, `task`, `reference_format`, and (for embedded
subtitles) `reference_stream`. The retained `manifest.json` has these fields;
full library paths are not embedded in the checked-in helper. It does not
choose a safe scheduling window for you.
`review_speech.py` checks validity, readability and temporal overlap and
prints private review windows. Keep its transcript output off Git.
`capture_speech.py` is an optional service-account-only raw diagnostic, not
an API or a way to turn unchecked output into a successful subtitle.
Do not install models, switch endpoints, or repeat intensive runs merely to
improve a numeric overlap score.
