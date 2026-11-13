# Mac Studio local AI

The Studio runs Whisper with Apple MLX and Ollama natively, not in Colima.
Nothing here changes the homeserver's existing Whisper endpoint. Open WebUI
and an HTTP adapter for Whisper are not installed; no Bazarr compatibility is
claimed.

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

## Whisper CLI

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
