#!/bin/bash
# As run on 2026-11-13 (sudo) from ~/Services/ai-staging, since deleted. The
# staged files are in macos/ and macos/ai/. Moves the Whisper model, Ollama and
# mlx-whisper into the _studio worker, then runs offline smoke tests.
set -euo pipefail
home=/var/lib/studio-worker
staging=/Users/dante/Services/ai-staging
hub=.cache/huggingface/hub
model=models--mlx-community--whisper-large-v3-mlx
blob=blobs/92/920d780c40297c7e6ebc030b57169f0111b350c4905fdfb03560c79dec210842
[[ "$(id -u)" == 0 ]]
[[ "$(dscl . -read /Users/_studio NFSHomeDirectory)" == "NFSHomeDirectory: $home" ]]

install -d -o _studio -g staff -m 700 \
    "$home/ollama" "$home/ollama/models" "$home/logs" "$home/.cache" \
    "$home/.cache/huggingface" "$home/$hub" "$home/$hub/blobs" \
    "$home/$hub/blobs/92" "$home/ai-tests"
ditto "/Users/dante/$hub/$model" "$home/$hub/$model"
ditto "/Users/dante/$hub/$blob" "$home/$hub/$blob"
chown -R _studio:staff "$home/$hub/$model"
chown _studio:staff "$home/$hub/$blob"
install -o _studio -g staff -m 600 "$staging/english.aiff" "$home/ai-tests/english.aiff"
install -o _studio -g staff -m 600 "$staging/spanish.aiff" "$home/ai-tests/spanish.aiff"

plutil -lint "$staging/com.danteb.studio-ollama.plist"
install -o root -g wheel -m 644 "$staging/com.danteb.studio-ollama.plist" \
    /Library/LaunchDaemons/com.danteb.studio-ollama.plist
launchctl bootstrap system /Library/LaunchDaemons/com.danteb.studio-ollama.plist

sudo -u _studio env HOME="$home" PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    uv tool install --python 3.13 --with 'certifi>=2026.10.18' mlx-whisper==0.4.3
sudo -u _studio env HOME="$home" PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    HF_HUB_OFFLINE=1 "$home/.local/bin/mlx_whisper" "$home/ai-tests/english.aiff" \
    --language en --task transcribe --model mlx-community/whisper-large-v3-mlx \
    --output-dir "$home/ai-tests" --output-format srt
sudo -u _studio env HOME="$home" PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    HF_HUB_OFFLINE=1 "$home/.local/bin/mlx_whisper" "$home/ai-tests/spanish.aiff" \
    --language es --task translate --model mlx-community/whisper-large-v3-mlx \
    --output-dir "$home/ai-tests" --output-format srt
printf '\nISOLATED_ENGLISH_SRT\n'
cat "$home/ai-tests/english.srt"
printf '\nISOLATED_SPANISH_TRANSLATION_SRT\n'
cat "$home/ai-tests/spanish.srt"
printf '\nISOLATED_CERTIFI\n'
sudo -u _studio "$home/.local/share/uv/tools/mlx-whisper/bin/python" \
    -c 'import certifi; print(certifi.__version__)'
printf '\nFORWARDING_PUBLIC_KEY\n'
cat "$home/.ssh/id_ed25519_transfer.pub"
