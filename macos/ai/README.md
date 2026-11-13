# Mac Studio local AI

The Studio can run Whisper with Apple MLX and Ollama natively, not in Colima.
Nothing here changes the homeserver's existing Whisper endpoint or Bazarr
settings. Open WebUI is not installed. Whisper large-v3 is a comparison
baseline, **not an established best model** for the target media. See
[speech model evaluation](SPEECH.md) before choosing a subtitle or translation
workflow.

## Provisioning

Install Homebrew's `ffmpeg` and `ollama` as the Homebrew owner, never as root.
The isolated `_studio` account has no admin rights or SSH login and uses the
private home `/var/lib/studio-worker` (mode 700). Install its pinned Whisper
CLI as that account; do not copy personal credentials or SSH keys into its
home:

```sh
sudo -u _studio env HOME=/var/lib/studio-worker PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin uv tool install --python 3.13 mlx-whisper==0.4.3
```

The Whisper model is `mlx-community/whisper-large-v3-mlx`; its first use
downloads it to the Hugging Face cache. Model downloads need internet; audio,
prompts and completions stay local. Keep private audio and outputs in private
directories. The Ollama model and logs live under `/var/lib/studio-worker`.
When transferring an existing Hugging Face cache, preserve the snapshot
symlinks and their referenced blobs, including any shared `hub/blobs` targets;
copying only the model directory may leave dangling links. Ensure all copied
files and directories are owned by `_studio` and private.

The LaunchDaemon is a system service running as `_studio`, so it starts without
a GUI login once the FileVault volume is unlocked. Install the plist from a
trusted checkout as root (not as a user-writable symlink); create the working
and log directories first as root:

```sh
sudo install -d -o _studio -g staff -m 700 /var/lib/studio-worker/ollama/models /var/lib/studio-worker/logs
sudo install -o root -g wheel -m 644 com.danteb.studio-ollama.plist /Library/LaunchDaemons/com.danteb.studio-ollama.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.danteb.studio-ollama.plist
```

The account and its private home must already exist. Run these commands from
this directory on the Studio. To update the daemon,
boot it out first, replace the plist with the same `install` command, then
bootstrap it again:

```sh
sudo launchctl bootout system/com.danteb.studio-ollama
```

The daemon listens only on `127.0.0.1:11434`, disables Ollama cloud features,
and defaults to one request at a time, one resident model, a four-request
queue, 4096 context tokens and a five-minute idle unload. These are defaults,
not a hard RAM cap: API clients can override context and keep-alive and can
request other locally installed models. Restrict local access and do not send
large-context or multiple-model workloads while Whisper, two x265 workers and
the 6 GB Colima VM are active. Monitor memory pressure and adjust workloads
if they compete; no combined-load capacity guarantee is implied.

Pull the 5.2 GB Q4 model once, then check actual structured output:

```sh
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3:8b
uv run --no-project python check-ollama.py
OLLAMA_HOST=127.0.0.1:11434 ollama ps
```

`ollama ps` reports GPU allocation while a model is resident. The checker
sends only synthetic diagnostic text. Ollama's schema constrains output shape,
not truth or safety: automation must independently validate all outputs and
initially produce read-only shadow recommendations. Never give the model shell,
deletion or restart authority.

## Experimental Bazarr-compatible adapter

The adapter implements the Bazarr Whisper provider's raw 16 kHz, mono,
signed 16-bit little-endian PCM uploads: `POST /asr?task=transcribe|translate
&language=<input-code>&output=srt&encode=false` and
`POST /detect-language?encode=false`. Its optional `video_file` query value is
ignored, never opened or logged. Other formats, encoded uploads, arbitrary
models and arbitrary paths are not supported. The only model is the offline
large-v3 snapshot at revision `49e6aa286ad60c14352c404340ded53710378a11`.
It is a baseline to compare, not a promise of Telugu translation quality.
Explicit English transcription disables previous-text conditioning to reduce
an observed repetition loop; other tasks retain the upstream default. This can
change consistency between audio windows and has not been speaker-reviewed.

The daemon listens on `127.0.0.1:9000`, does not authenticate clients, disables
HTTP access logs, and runs as `_studio`. One job is accepted at a time; busy
requests fail with 503. Each job loads a short-lived model process, which exits
afterward so its memory can be reclaimed. Raw audio is limited to two hours
(230,400,000 bytes), upload time to two minutes, and inference time to two
hours. Temporary audio is private to the service account and removed after
the job in normal operation; an abrupt process or system termination can
leave private temporary files that require cleanup. Allow enough free disk for
two copies of the upload and enough unified memory for Whisper, the audio and
other workloads. Invalid, reversed or out-of-order SRT timestamps fail the
request rather than being saved; this does not detect missing speech or
hallucinations.

Prepare the isolated account's model cache, including the pinned snapshot and
all referenced blobs, as described above. Ensure `_studio` can read/traverse
the shared Homebrew runtime without admin membership. From a trusted staging
directory containing `pyproject.toml`, `uv.lock`, `whisper_adapter.py`,
`whisper_worker.py` and the plist:

```sh
sudo install -d -o _studio -g staff -m 700 /var/lib/studio-worker/ai /var/lib/studio-worker/tmp /var/lib/studio-worker/logs
sudo install -o _studio -g staff -m 600 pyproject.toml uv.lock whisper_adapter.py whisper_worker.py /var/lib/studio-worker/ai/
sudo -u _studio env HOME=/var/lib/studio-worker TMPDIR=/var/lib/studio-worker/tmp PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin uv sync --project /var/lib/studio-worker/ai --frozen --no-dev
sudo install -o root -g wheel -m 644 com.danteb.studio-whisper.plist /Library/LaunchDaemons/com.danteb.studio-whisper.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.danteb.studio-whisper.plist
```

`uv.lock` includes all dependencies; synchronization may download packages but
model inference is offline. Restart by booting out the system job, replacing
its files and bootstrapping it again. The service is experimental: do not
change Bazarr to use it until a full episode is evaluated against independently
verified reference subtitles, including translation meaning, omissions,
hallucinations and timing.

Bazarr has no dedicated authentication header for this provider. A later
integration needs a restricted authenticated transport from Bazarr's container
to the Studio's loopback listener (for example a dedicated SSH forwarding
identity and tightly restricted local gateway). A host-loopback tunnel alone
is not automatically reachable from a container. Do not expose port 9000 on
the LAN or WAN, and do not assume DNS itself authenticates traffic. Verify the
installed provider's error handling first: provider versions that save
non-2xx response bodies as subtitles can turn overload or inference errors
into invalid subtitle files. No live cutover or tunnel is configured here.

`bazarr-whisper-status.patch` is a narrow compatibility patch for the installed
Bazarr provider inspected during this evaluation. It rejects non-2xx responses
from both endpoints without following redirects, before logging or saving their
contents. It is not installed automatically. Apply it only to a disposable
copy of the exact provider first, using `git apply --unidiff-zero` (the final
hunk has no trailing context), and run
`uv run --no-project python check-bazarr-whisper-patch.py <patched-copy>`; fail
closed if the patch no longer applies or the checks fail. A deployment needs a
version-pinned, repeatable way to deliver and revalidate the patch on every
Bazarr update. Do not edit the running container or enable the provider until
that deployment and the subtitle quality evaluation are complete.

For multi-audio files, the inspected provider defaults to the first audio
stream when translating and no audio language matches the requested subtitle
language. For example, Vishnu Puran S01E01 has Hindi first and Telugu third;
an explicit Telugu benchmark does not prove that Bazarr will select Telugu.
Do not silently change global audio-language preferences to work around this.

## Whisper baseline CLI

```sh
sudo -u _studio env HOME=/var/lib/studio-worker PATH=/var/lib/studio-worker/.local/bin:/opt/homebrew/bin:/usr/bin:/bin mlx_whisper /path/to/audio.wav --model mlx-community/whisper-large-v3-mlx --language en --task transcribe --output-format srt --output-dir /path/to/output
sudo -u _studio env HOME=/var/lib/studio-worker PATH=/var/lib/studio-worker/.local/bin:/opt/homebrew/bin:/usr/bin:/bin mlx_whisper /path/to/spanish.wav --model mlx-community/whisper-large-v3-mlx --language es --task translate --output-format srt --output-dir /path/to/output
```

Provide input and output paths accessible to `_studio`; avoid granting that
account access to the user's home or credentials. Translation produces English,
not an arbitrary target language. Omit
`--language` for automatic input-language detection. CLI processes load their
own model; avoid concurrent invocations. These commands do not implement
Bazarr's multipart/raw-PCM API or `/detect-language`.

For later server automation, use a separately managed authenticated SSH tunnel
that binds its client end to loopback, and restrict its account and consumers.
Ollama itself has no authentication; a tunnel grants access to the full API,
not just inference, and local processes on either host may reach its listener.
Do not expose it directly on the LAN or internet.

## Runtime choice

Ollama is the simplest fit for this use: a local API, schema-constrained JSON,
model management and Apple GPU support. `llama.cpp` offers more direct GGUF
tuning and a server, but requires more operational choices. MLX is excellent
for Apple-specific inference and is already used by Whisper; an MLX LLM server
would add another model/runtime workflow. Qwen3:8b is a modest starting point,
not a guarantee of judgement quality; evaluate representative cases before
relying on recommendations.

References: [Ollama structured output](https://docs.ollama.com/capabilities/structured-outputs),
[Ollama FAQ](https://docs.ollama.com/faq), [Qwen3:8b](https://ollama.com/library/qwen3:8b),
and [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper).
