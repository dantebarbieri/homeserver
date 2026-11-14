#!/bin/bash
# As run on 2026-11-13 (sudo) from ~/Services/ai-staging, since deleted. The
# staged files are in macos/ai/ and macos/. Installs the experimental Whisper
# API under the _studio worker and copies the private benchmark inputs.
set -euo pipefail
[[ "$(id -u)" == 0 ]]
home=/var/lib/studio-worker
staging=/Users/dante/Services/ai-staging
install -d -o _studio -g staff -m 700 \
    "$home/ai" "$home/tmp" "$home/logs" "$home/ai-tests/benchmark-20261113"
for file in pyproject.toml uv.lock whisper_adapter.py whisper_worker.py; do
    install -o _studio -g staff -m 600 "$staging/$file" "$home/ai/$file"
done
sudo -u _studio env HOME="$home" TMPDIR="$home/tmp" \
    PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
    uv sync --project "$home/ai" --frozen --no-dev
for file in english.pcm telugu.pcm japanese.pcm \
    english-reference.srt telugu-reference.ass japanese-reference.ass; do
    install -o _studio -g staff -m 600 "$staging/benchmark-20261113/$file" \
        "$home/ai-tests/benchmark-20261113/$file"
done
plutil -lint "$staging/com.danteb.studio-whisper.plist"
install -o root -g wheel -m 644 "$staging/com.danteb.studio-whisper.plist" \
    /Library/LaunchDaemons/com.danteb.studio-whisper.plist
launchctl bootstrap system /Library/LaunchDaemons/com.danteb.studio-whisper.plist
install -o root -g wheel -m 644 "$staging/001-studio-worker.conf" \
    /etc/ssh/sshd_config.d/001-studio-worker.conf
/usr/sbin/sshd -t
if sudo -u _studio /bin/test -r /Users/dante/.ssh/id_ed25519; then
    echo "Worker can read the administration key; stop deployment." >&2
    exit 1
fi
printf 'Adapter installed under isolated worker; benchmark copies ready.\n'
