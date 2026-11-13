#!/bin/bash
# As run on 2026-11-13 (sudo) from ~/Services/ai-staging/deploy-20261113, since
# deleted. Adds the Telugu faster-whisper route to the installed adapter: backs
# up the old code, installs the server's faster-whisper snapshot for _studio,
# syncs the locked venv and restarts. The first run stopped at `uv sync`
# because _studio could not read the staging directory; the `cd` below is the
# fix that a resume run applied.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

STAGE=/Users/dante/Services/ai-staging/deploy-20261113
SRC=/Users/dante/Services/ai-staging/telugu-faster-whisper-20261113/hf/hub/models--Systran--faster-whisper-large-v3
WORKER_HOME=/var/lib/studio-worker
HUB=$WORKER_HOME/.cache/huggingface/hub
MODEL=$HUB/models--Systran--faster-whisper-large-v3
BACKUP=$WORKER_HOME/ai-tests/deploy-20261113-backup
FILES="pyproject.toml uv.lock whisper_adapter.py whisper_worker.py"
REV=edaa852ec7e145841d8ffdb056a99866b5f0a478

cd "$STAGE"
shasum -a 256 -c SHA256SUMS
[ -d "$SRC/snapshots/$REV" ]
[ -d "$HUB" ] && [ ! -e "$MODEL" ] && [ ! -e "$BACKUP" ]

install -d -o _studio -g staff -m 700 "$BACKUP"
for f in $FILES; do cp -p "$WORKER_HOME/ai/$f" "$BACKUP/"; done

ditto "$SRC" "$MODEL"
# Hub-level shared blobs sit outside the model directory; copy their content.
for link in "$MODEL"/blobs/*; do
  if [ -L "$link" ]; then
    rm "$link"
    cp -L "$SRC/blobs/$(basename "$link")" "$link"
  fi
done
chown -R _studio:staff "$MODEL"
chmod -R go-rwx "$MODEL"
if find "$MODEL/snapshots" -type l ! -exec test -e {} \; -print | grep -q .; then
  echo "dangling snapshot links" >&2; exit 1
fi
cmp "$MODEL/snapshots/$REV/model.bin" "$SRC/snapshots/$REV/model.bin"

for f in $FILES; do install -o _studio -g staff -m 600 "$f" "$WORKER_HOME/ai/$f"; done
cd "$WORKER_HOME/ai"
sudo -u _studio env HOME=$WORKER_HOME TMPDIR=$WORKER_HOME/tmp \
  PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  uv sync --project "$WORKER_HOME/ai" --frozen --no-dev
sudo -u _studio env HOME=$WORKER_HOME HF_HUB_OFFLINE=1 \
  "$WORKER_HOME/ai/.venv/bin/python" -I -c "
from huggingface_hub import snapshot_download
import faster_whisper, ctranslate2
snapshot_download('Systran/faster-whisper-large-v3', revision='$REV', local_files_only=True)
print('faster-whisper', faster_whisper.__version__, 'ctranslate2', ctranslate2.__version__)"

launchctl kickstart -k system/com.danteb.studio-whisper
sleep 5
launchctl print system/com.danteb.studio-whisper | grep -E '(state|pid) =' || true
echo "deployed; backup in $BACKUP"
