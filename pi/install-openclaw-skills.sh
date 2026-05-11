#!/usr/bin/env bash
# install-openclaw-skills.sh — deploy the travel-agent + home-scout workspace,
# scripts, and cron jobs to the Pi. Runs from the dev machine; SSHes into the
# Pi and drives everything from the Pi's local /home/openclaw/repos/homeserver
# clone.
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

echo "[3/5] install workspace files (TRAVEL.md + HOME.md + skills/)…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw bash -c "
  set -e
  WORKSPACE=/home/openclaw/.openclaw/workspace
  SOURCE=/home/openclaw/repos/homeserver/pi/openclaw-workspace

  # Preamble docs
  install -m 644 \"\$SOURCE/TRAVEL.md\" \"\$WORKSPACE/TRAVEL.md\"
  install -m 644 \"\$SOURCE/HOME.md\"   \"\$WORKSPACE/HOME.md\"

  # Travel skills
  for skill in travel-dispatch travel-deep-plan travel-alter-plan \
               travel-seasonality-synth travel-watch travel-fx travel-holidays; do
    mkdir -p \"\$WORKSPACE/skills/\$skill\"
    install -m 644 \"\$SOURCE/skills/\$skill/SKILL.md\" \
                   \"\$WORKSPACE/skills/\$skill/SKILL.md\"
  done

  # home-scout skill (SKILL.md + config files)
  mkdir -p \"\$WORKSPACE/skills/home-scout\"
  install -m 644 \"\$SOURCE/skills/home-scout/SKILL.md\"           \"\$WORKSPACE/skills/home-scout/SKILL.md\"
  install -m 644 \"\$SOURCE/skills/home-scout/neighborhoods.yaml\" \"\$WORKSPACE/skills/home-scout/neighborhoods.yaml\"
  install -m 644 \"\$SOURCE/skills/home-scout/config.yaml\"        \"\$WORKSPACE/skills/home-scout/config.yaml\"

  echo \"  workspace files installed\"
"'

echo "[4/5] install python helper scripts…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw bash -c "
  set -e
  SCRIPTS=/home/openclaw/.openclaw/scripts
  SOURCE=/home/openclaw/repos/homeserver/pi/openclaw-scripts
  mkdir -p \"\$SCRIPTS\"
  install -m 755 \"\$SOURCE/travel-fx.py\"          \"\$SCRIPTS/travel-fx.py\"
  install -m 755 \"\$SOURCE/travel-holidays.py\"    \"\$SCRIPTS/travel-holidays.py\"
  install -m 755 \"\$SOURCE/home_scout_math.py\"    \"\$SCRIPTS/home_scout_math.py\"
  install -m 755 \"\$SOURCE/home_scout_fetch.py\"   \"\$SCRIPTS/home_scout_fetch.py\"
  install -m 755 \"\$SOURCE/home_scout_score.py\"   \"\$SCRIPTS/home_scout_score.py\"
  install -m 755 \"\$SOURCE/home_scout_notify.py\"  \"\$SCRIPTS/home_scout_notify.py\"
  echo \"  scripts installed\"
"'

echo "[5/5] upsert travel-agent + home-scout cron jobs…" >&2
ssh -t "$PI_HOST" 'sudo -u openclaw python3 \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/upsert-jobs.py \
  /home/openclaw/.openclaw/cron/jobs.json \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/travel-jobs.json'
ssh -t "$PI_HOST" 'sudo -u openclaw python3 \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/upsert-jobs.py \
  /home/openclaw/.openclaw/cron/jobs.json \
  /home/openclaw/repos/homeserver/pi/openclaw-jobs/home-scout-jobs.json'

echo ""
echo "Install complete. Add NTFY_TOPIC_HOME_SCOUT to ~/.openclaw/secrets.env on the Pi"
echo "if not already present, then restart the gateway to pick up workspace changes:"
echo "  ssh $PI_HOST 'XDG_RUNTIME_DIR=/run/user/\$(id -u openclaw) \\"
echo "    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u openclaw)/bus \\"
echo "    sudo -u openclaw systemctl --user restart openclaw-gateway.service'"
echo ""
echo "Verify jobs: ssh $PI_HOST 'sudo cat /home/openclaw/.openclaw/cron/jobs.json | python3 -m json.tool | grep -A1 \"\\\"name\\\":\\\"\"'"
