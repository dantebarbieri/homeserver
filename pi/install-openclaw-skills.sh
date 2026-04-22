#!/usr/bin/env bash
# install-openclaw-skills.sh — deploy the travel-agent workspace + scripts
# + cron jobs to the Pi. Runs from the dev machine; SSHes into the Pi and
# drives everything from the Pi's local /home/openclaw/repos/homeserver clone.
#
# Prerequisite: commits must already be pulled on the Pi. This script
# does NOT pull for you — safer to let you audit the diff first.
#
# Idempotent. Safe to re-run.
#
# Usage: ./install-openclaw-skills.sh [pi-ssh-host]   (default host: "pi")
set -euo pipefail

PI_HOST="${1:-pi}"

echo "[1/5] verify Pi repo is up to date…" >&2
ssh "$PI_HOST" 'sudo -u openclaw bash -c "
  cd /home/openclaw/repos/homeserver
  git fetch --quiet
  if ! git diff --quiet HEAD origin/main -- pi/; then
    echo \"REPO AHEAD — run: sudo -u openclaw git -C /home/openclaw/repos/homeserver pull --ff-only\" >&2
    exit 11
  fi
  git -C /home/openclaw/repos/homeserver log --oneline -1
"'

echo "[2/5] apply pending sqlite migrations…" >&2
ssh "$PI_HOST" 'sudo -u openclaw python3 \
  /home/openclaw/repos/homeserver/pi/apply-migrations.py \
  /var/lib/openclaw/state.db \
  /home/openclaw/repos/homeserver/pi/sqlite-migrations/'

echo "[3/5] install workspace files (TRAVEL.md + skills/)…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw bash -c "
  set -e
  WORKSPACE=/home/openclaw/.openclaw/workspace
  SOURCE=/home/openclaw/repos/homeserver/pi/openclaw-workspace

  # TRAVEL.md — install or update.
  install -m 644 \"\$SOURCE/TRAVEL.md\" \"\$WORKSPACE/TRAVEL.md\"

  # skills/ — rsync so new skill files appear + existing ones update, but
  # unrelated directories (repo-advisor, etc.) stay put.
  for skill in travel-dispatch travel-deep-plan travel-alter-plan \
               travel-seasonality-synth travel-watch travel-fx travel-holidays; do
    mkdir -p \"\$WORKSPACE/skills/\$skill\"
    install -m 644 \"\$SOURCE/skills/\$skill/SKILL.md\" \
                   \"\$WORKSPACE/skills/\$skill/SKILL.md\"
  done

  echo \"  workspace files installed\"
"'

echo "[4/5] install python helper scripts (travel-fx.py, travel-holidays.py)…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw bash -c "
  set -e
  SCRIPTS=/home/openclaw/.openclaw/scripts
  SOURCE=/home/openclaw/repos/homeserver/pi/openclaw-scripts
  mkdir -p \"\$SCRIPTS\"
  install -m 755 \"\$SOURCE/travel-fx.py\"       \"\$SCRIPTS/travel-fx.py\"
  install -m 755 \"\$SOURCE/travel-holidays.py\" \"\$SCRIPTS/travel-holidays.py\"
  echo \"  scripts installed\"
"'

echo "[5/5] upsert travel-agent cron jobs + remove foo-cron-job-bar…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw python3 \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/upsert-jobs.py \
  /home/openclaw/.openclaw/cron/jobs.json \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/travel-jobs.json'

echo ""
echo "Install complete. Restart the gateway to pick up workspace changes:"
echo "  ssh $PI_HOST 'XDG_RUNTIME_DIR=/run/user/\$(id -u openclaw) \\"
echo "    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u openclaw)/bus \\"
echo "    sudo -u openclaw systemctl --user restart openclaw-gateway.service'"
echo ""
echo "Verify with: ssh $PI_HOST 'sudo cat /home/openclaw/.openclaw/cron/jobs.json | python3 -m json.tool | grep -A1 \\\"\\\"name\\\":\\\"'"
