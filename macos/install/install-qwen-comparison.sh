#!/bin/bash
# As run on 2026-11-13 (sudo). Copies the Qwen3-ASR comparison models from the
# admin's Hugging Face cache (since deleted) into the worker's ai-tests/.
set -euo pipefail
[[ "$(id -u)" == 0 ]]
home=/var/lib/studio-worker
hub=/Users/dante/.cache/huggingface/hub
models="$home/ai-tests/models"
install -d -o _studio -g staff -m 700 "$models" "$models/asr" "$models/aligner"
cp -RL "$hub/models--Qwen--Qwen3-ASR-1.7B/snapshots/7278e1e70fe206f11671096ffdd38061171dd6e5/." "$models/asr/"
cp -RL "$hub/models--Qwen--Qwen3-ForcedAligner-0.6B/snapshots/c7cbfc2048c462b0d63a45797104fc9db3ad62b7/." "$models/aligner/"
chown -R _studio:staff "$models"
chmod -R u+rwX,go-rwx "$models"
sudo -u _studio env HOME="$home" PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    uv tool install --python 3.13 --with 'certifi>=2026.10.18' mlx-qwen3-asr==0.4.4
printf 'Private Qwen comparison models and CLI ready; no inference started.\n'
