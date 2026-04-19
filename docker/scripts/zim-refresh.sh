#!/usr/bin/env bash
# zim-refresh.sh — print a checklist of ZIM files that need refreshing.
# Does NOT auto-download; downloads should go through your torrent client
# of choice (kiwix.org HTTP mirror is slow and stresses their bandwidth).
#
# Reads ${OPENCLAW_V3_BASE}/zim/, compares the YYYY-MM date encoded in each
# filename against an upstream-suggested cadence, and prints the ones that
# are stale.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
: "${OPENCLAW_V3_BASE:?set OPENCLAW_V3_BASE in .env}"

ZIM_DIR="${OPENCLAW_V3_BASE}/zim"

# Stem → max-age-in-days
declare -A STEMS=(
  [wikipedia_en_all_maxi]=180
  [wikivoyage_en_all_maxi]=120
  [wiktionary_en_all_nopic]=180
  [travel.stackexchange.com_en_all]=180
  [wikimed_en_all_maxi]=365
)

today_epoch=$(date -u +%s)

printf '%-40s %-12s %-10s %s\n' "STEM" "FOUND" "AGE(d)" "STATUS"
printf '%-40s %-12s %-10s %s\n' "----" "-----" "------" "------"

for stem in "${!STEMS[@]}"; do
  max_age="${STEMS[$stem]}"
  # shellcheck disable=SC2012
  match=$(ls -1 "$ZIM_DIR"/${stem}_*.zim 2>/dev/null | sort | tail -1 || true)
  if [ -z "$match" ]; then
    printf '%-40s %-12s %-10s %s\n' "$stem" "MISSING" "-" "DOWNLOAD"
    continue
  fi
  date_part=$(basename "$match" .zim | sed -E "s/^${stem}_//")
  zim_epoch=$(date -u -d "${date_part}-01" +%s 2>/dev/null || \
              date -u -j -f "%Y-%m-%d" "${date_part}-01" +%s 2>/dev/null || echo 0)
  age_days=$(( (today_epoch - zim_epoch) / 86400 ))
  if [ "$age_days" -gt "$max_age" ]; then
    status="STALE  (max ${max_age}d)"
  else
    status="ok     (max ${max_age}d)"
  fi
  printf '%-40s %-12s %-10s %s\n' "$stem" "$date_part" "$age_days" "$status"
done

echo
echo "ZIM index: https://download.kiwix.org/zim/"
echo "Torrents:  follow the 'magnet' / 'torrent' links from the index."
