# Mac Studio local AI

The Studio runs Whisper with Apple MLX and Ollama natively (MLX needs macOS
Metal, so they cannot run in a Linux container or VM).
Dante decided to move Bazarr's Whisper subtitles from the server's GPU
`whisperasr` to this adapter, accepting that Telugu may come out somewhat
worse than the server's, since Telugu is a minority of the subtitles. See
[Bazarr transport and cutover](#bazarr-transport-and-cutover) for the
connection and its status. Open WebUI is not installed. Whisper large-v3 is a
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
large-context or multiple-model workloads while Whisper and two x265 workers
are active. Monitor memory pressure and adjust workloads
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

## Ollama transport

The *arr maintenance integration uses `qwen3.5:9b-q4_K_M` (6.6 GB), selected
through [read-only model comparisons and deterministic guard tests](../../docker/docs/ARR-MAINT-AI.md).
Keep the explicit GGUF tag: `qwen3.5:9b` selected a different runtime variant
on this Mac which returned HTTP 501 for schema-constrained output.
The old `qwen3:8b` remains available, but is not the integration's selected model.

The server's `studio-ollama` container reuses the SSH forward image with
`STUDIO_PORT=11434` and its own `_arrmaint` identity. Only `lidarr-maint`,
`radarr-maint` and `sonarr-maint` share `arr-ai` with it. There is no published
port, proxy host or access through Bazarr's Whisper network.
The client sends the upstream loopback `Host` header through the tunnel;
Ollama otherwise rejects POSTs using the Docker service hostname with HTTP 403.
Do not weaken Ollama's origin protection with a wildcard to work around this.

Provision it independently of Bazarr:

```sh
# Server: create a private key directory; never copy the private key to Studio.
sudo install -d -o danteb -m 700 /srv/docker/data/studio-ollama-tunnel
umask 077
ssh-keygen -t ed25519 -N '' -C arr-maint@homeserver -f /srv/docker/data/studio-ollama-tunnel/id_ed25519
ssh studio cat /etc/ssh/ssh_host_ed25519_key.pub | awk '{print "ai-studio", $1, $2}' > /srv/docker/data/studio-ollama-tunnel/known_hosts
```

Copy only `id_ed25519.pub` to a trusted Studio staging directory. From a trusted
checkout of this directory on Studio:

```sh
sudo /bin/bash provision-ai-forwarding.sh ollama /path/to/id_ed25519.pub
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3.5:9b-q4_K_M
```

The installer verifies candidate/live sshd policy and preserves the admin
policy. `_arrmaint` uses `/var/empty`, has no usable password, belongs to the
Remote Login group but not `admin`/`wheel`, and cannot open a session. Its
root-owned `/etc/ssh/arr-maint-forwarding-keys` and
`/etc/ssh/sshd_config.d/003-arr-maint-forwarding.conf` restrict its server key
to forwarding only `127.0.0.1:11434` from the homeserver's address.
`provision-bazarr-forwarding.sh` now delegates its unchanged Whisper setup to
the same installer; the two accounts, keys and allowed destinations stay separate.

Enable the `arr-ai` Compose profile and start in `ARR_AI_MODE=shadow`, then
switch to `auto` only after checking real recommendations. See the integration
document for rollout, verification, budgets and rollback.

To retire the connection, first disable model assistance and stop
`studio-ollama`. Remove its key directory on the server and the two
`arr-maint-forwarding-*`/`003-arr-maint-forwarding.conf` files on Studio;
remove `_arrmaint` from `com.apple.access_ssh`, then delete that service account.
Validate sshd before closing the existing admin session. Ollama and the
Whisper/Tdarr accounts need not be changed.

## Bazarr-compatible adapter

The adapter implements the Bazarr Whisper provider's raw 16 kHz, mono,
signed 16-bit little-endian PCM uploads: `POST /asr?task=transcribe|translate
&language=<input-code>&output=srt&encode=false` and
`POST /detect-language?encode=false`. Its optional `video_file` query value is
ignored, never opened or logged. Other formats, encoded uploads, arbitrary
models and arbitrary paths are not supported.

Two engines serve requests, each from an offline, pinned snapshot:

- **Telugu input (`language=te`)** copies the server's approach:
  faster-whisper 1.2.1 and CTranslate2 4.8.1 with the server's
  `Systran/faster-whisper-large-v3` snapshot
  `edaa852ec7e145841d8ffdb056a99866b5f0a478`, beam size 5 and otherwise
  default decoding. MLX Whisper has no beam search, and its Telugu output was
  much more repetitive than the server's. CTranslate2 has no Apple GPU
  backend, so this runs on 12 CPU threads in float32 and is far slower than
  the server's GPU (see [SPEECH.md](SPEECH.md#telugu-on-the-cpu)).
- **Everything else**, including `/detect-language`, uses MLX Whisper with
  `mlx-community/whisper-large-v3-mlx` snapshot
  `49e6aa286ad60c14352c404340ded53710378a11`. Explicit English
  transcription disables previous-text conditioning to reduce an observed
  repetition loop; other tasks retain the upstream default. This can change
  consistency between audio windows and has not been speaker-reviewed.

Neither engine promises good translation quality.

The daemon listens on `127.0.0.1:9000`, does not authenticate clients, disables
HTTP access logs, and runs as `_studio`. One job is accepted at a time; busy
requests fail with 503. Each job loads a short-lived model process, which exits
afterward so its memory can be reclaimed. Raw audio is limited to four hours
(460,800,000 bytes) because long Telugu mythological films run past three
hours, and upload time to two minutes. Inference is limited to two hours, or
for Telugu to twice the audio's duration. Temporary audio is private to the service account and removed after
the job in normal operation; an abrupt process or system termination can
leave private temporary files that require cleanup. Allow enough free disk for
two copies of the upload and enough unified memory for Whisper, the audio and
other workloads. The worker sorts bounded out-of-order cues, trims overlaps,
and estimates an end time for bounded reversed or zero-duration cues. It logs
repair counts without subtitle text; unparseable, extreme, or unsalvageable
timings still fail the request. Reordering and estimated ends are not verified
against the audio, and repairs cannot fix missing or hallucinated speech.

Prepare the isolated account's model cache with both pinned snapshots and all
their referenced blobs, as described above. The faster-whisper snapshot is the
same `Systran/faster-whisper-large-v3` revision the server's `whisperasr`
uses. Ensure `_studio` can read/traverse
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
model inference is offline. Run `uv` as `_studio` from a directory it can read
(for example `cd /var/lib/studio-worker/ai` first): started from a private
staging directory it fails with `Permission denied`. Restart by booting out the
system job, replacing its files and bootstrapping it again.

## Bazarr transport and cutover

**Live since 2026-11-13.** Bazarr's endpoint is
`http://studio-whisper:9000`, job timeout `30000`, and its pre-existing
connection timeout `60` is unchanged. The real provider in the running
patched Bazarr container completed `/detect-language`, English transcription
(8.88 seconds of synthetic audio, 3 cues in 1.45 seconds) and Telugu-to-English
translation (a 30-second retained-audio excerpt, 6 cues in 29.78 seconds).
All three requests returned HTTP 200; both SRTs had valid, nonoverlapping
timing. No library media/subtitle files or audio-language preferences changed.
This proves the configured request path, not translation quality.

Bazarr's Whisper provider cannot authenticate, so it reaches the adapter
through an SSH tunnel at `http://studio-whisper:9000`. The server's
`studio-whisper` container ([`docker/dockerfiles/studio-whisper-tunnel`](../../docker/dockerfiles/studio-whisper-tunnel),
defined in `docker/compose.ai.yml`) holds one SSH local forward from its port
9000 to the Studio's `127.0.0.1:9000`, logging in as the forward-only account
`_bazarr`. It runs as the server's `HOST_UID` with a read-only root
filesystem, no capabilities and a read-only `/state` holding its key and the
pinned Studio host key. Only Bazarr shares its Docker network; no port is
published and NPM does not proxy it. Anything on that network can use the
unauthenticated adapter, so attach nothing else to it. Never expose port 9000
on the LAN or WAN; a private DNS name does not authenticate anyone.
The tunnel resolves `ai-studio.home.arpa` through AdGuard at `192.168.50.100`;
the server's public fallback resolvers cannot answer that private name.
The main Compose file reserves `10.253.240.8/29` for this network because the
default Docker pools are exhausted; it does not overlap the transfer network's
`10.253.240.0/29` or the host's other routes.

On the Studio, `_bazarr` is a hidden standard account with no usable password or
usable home (`/var/empty`), outside `admin` and `wheel`. macOS PAM requires
its account shell to be `/bin/sh` even for forwarding-only logins;
`MaxSessions 0` denies all SSH shell, command and subsystem channels,
with `ForceCommand /usr/bin/false` as an additional restriction. Its public key is the
only line of the root-owned `/etc/ssh/bazarr-forwarding-keys`, restricted to
the server's address and to forwarding `127.0.0.1:9000`.
[`002-bazarr-forwarding.conf`](002-bazarr-forwarding.conf) applies the same
policy in sshd: public keys from that file only, local forwards to
`127.0.0.1:9000` only, and no remote or socket forwards, TTY, agent, X11,
tunnel, rc file or command. Remote Login admits only `com.apple.access_ssh`
members, so the account joins that group. This path is separate from the
Studio-to-server Tdarr transfer tunnel; neither depends on the other.

Set it up in this order, keeping an admin SSH session to the Studio open:

1. On the server, as the `HOST_UID` account (`danteb`), create the client
   key and pin the Studio's host key, read over the already-verified admin
   SSH connection rather than `ssh-keyscan`:

   ```sh
   sudo install -d -o danteb -m 700 /srv/docker/data/studio-whisper-tunnel
   ssh-keygen -t ed25519 -N '' -C bazarr-whisper@homeserver -f /srv/docker/data/studio-whisper-tunnel/id_ed25519
   ssh studio cat /etc/ssh/ssh_host_ed25519_key.pub | awk '{print "ai-studio", $1, $2}' > /srv/docker/data/studio-whisper-tunnel/known_hosts
   ```

2. Copy `id_ed25519.pub` (public only) to the Studio and, from a trusted
   checkout of this directory, run
   `sudo ./provision-bazarr-forwarding.sh id_ed25519.pub`. The script creates
   or reuses `_bazarr`, then checks a candidate sshd configuration (syntax,
   `_bazarr`'s effective forwarding policy, and that `dante`'s policy is
   unchanged) before installing anything. It re-checks the live
   configuration afterwards and removes the drop-in if that fails. macOS
   starts sshd per connection, so a bad drop-in would block new SSH logins.
3. Deploy from `main` through the main Compose entry point: build with
   `docker compose build --pull studio-whisper bazarr`, then
   `docker compose up -d --no-deps studio-whisper bazarr`.
   Check `docker compose logs studio-whisper` and reach the adapter from
   Bazarr. A GET to `/asr` returns 405; only POST invokes inference.
4. In Bazarr's Whisper provider settings, set the endpoint to
   `http://studio-whisper:9000` and the transcription/translation timeout to
   `30000` seconds; leave the connection timeout alone. Bazarr waits for the
   whole response within this read timeout, and a four-hour Telugu film can
   take up to eight hours on the CPU. The values are `whisperai.endpoint` and
   `whisperai.timeout` in `${DATA}/bazarr/config/config/config.yaml`.

To roll back, point the endpoint back at `http://whisperasr:9000` and
restore its previous `10800`-second job timeout (connection timeout `60`).
The server service remains running. The private
`/srv/docker/data/bazarr/config/studio-migration-20261113/` directory holds
the pre-cutover config, a consistent SQLite backup and aggregate request
results; the original image is tagged `bazarr-before-studio:20261113`.
Those backups contain credentials: never commit or print them. A normal
endpoint rollback does not require restoring the database.

To remove the transport, delete the `studio-whisper`
service and network from `compose.ai.yml` and `compose.starr.yml`, delete
its IPAM definition from `docker-compose.yml`, delete
`/srv/docker/data/studio-whisper-tunnel`, and on the Studio run
`sudo dseditgroup -o edit -d _bazarr -t user com.apple.access_ssh`, delete
`/etc/ssh/sshd_config.d/002-bazarr-forwarding.conf` and
`/etc/ssh/bazarr-forwarding-keys`, then `sudo dscl . -delete /Users/_bazarr`.

Bazarr's image is built from [`docker/dockerfiles/bazarr`](../../docker/dockerfiles/bazarr).
It patches the upstream Whisper provider to reject non-2xx responses from
both endpoints without following redirects, before logging or saving their
contents (upstream saves error bodies as subtitles). Every edit must match
exactly once, and the build then exercises the patched methods with
synthetic 200, 302, 400 and 503 responses. Any upstream change that breaks
either step fails the build, so the daily update keeps the previous Bazarr
container and reports the failure. Test a change against a provider file
before committing:

```sh
uv run --no-project python docker/dockerfiles/bazarr/patch_whisperai.py <copy-of-whisperai.py>
uv run --no-project python docker/dockerfiles/bazarr/check_whisperai.py <copy-of-whisperai.py>
```

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
