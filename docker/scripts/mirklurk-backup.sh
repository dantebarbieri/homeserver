#!/usr/bin/env bash
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/backups}"
MW_DB_SERVER="${MW_DB_SERVER:-mirklurk-db}"
MW_DB_NAME="${MW_DB_NAME:-mirklurk}"
MW_DB_USER="${MW_DB_USER:-mirklurk}"
MW_DB_PASSWORD_FILE="${MW_DB_PASSWORD_FILE:-/run/secrets/MIRKLURK_DB_PASSWORD}"

case "${1:-}" in
  --healthcheck)
    if [[ -e "$BACKUP_DIR/.last-failure" ]] ||
       [[ ! -f "$BACKUP_DIR/.last-success" ]] ||
       [[ -z "$(find "$BACKUP_DIR/.last-success" -mmin -390 -print)" ]]; then
      echo "MirkLurk backup missing, failed, or older than 6.5 hours." >&2
      exit 1
    fi
    exit 0
    ;;
  --once) ;;
  "")
    while true; do
      if bash "$0" --once; then
        sleep 21600
      else
        echo "MirkLurk backup failed; retrying in five minutes." >&2
        sleep 300
      fi
    done
    ;;
  *)
    echo "Usage: $0 [--once|--healthcheck]" >&2
    exit 2
    ;;
esac

temporary=""
finish() {
  local status=$?
  trap - EXIT
  if [[ -n "$temporary" ]]; then
    rm -f -- "$temporary/dump.sql.gz" "$temporary/weekly.sql.gz" || status=1
    rmdir -- "$temporary" || status=1
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "MirkLurk database backup failed; existing complete dumps were preserved." >&2
    touch "$BACKUP_DIR/.last-failure" ||
      echo "Could not write backup failure marker." >&2
  fi
  exit "$status"
}
trap finish EXIT

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
if [[ ! -r "$MW_DB_PASSWORD_FILE" ]]; then
  echo "Cannot read the MirkLurk database password file." >&2
  exit 1
fi
password="$(cat "$MW_DB_PASSWORD_FILE")"
if [[ -z "$password" ]]; then
  echo "MirkLurk database password file is empty." >&2
  exit 1
fi

temporary="$(mktemp -d "$BACKUP_DIR/.mirklurk-backup.XXXXXX")"
today="$(date -u +%F)"
MYSQL_PWD="$password" mariadb-dump \
  --host="$MW_DB_SERVER" --port=3306 --user="$MW_DB_USER" \
  --single-transaction --quick --skip-lock-tables --no-tablespaces \
  --default-character-set=utf8mb4 --hex-blob "$MW_DB_NAME" |
  gzip > "$temporary/dump.sql.gz"
unset password

gzip -t "$temporary/dump.sql.gz"
# A successful client can dump an empty, not-yet-installed database.
if ! gzip -cd "$temporary/dump.sql.gz" |
     awk '/^CREATE TABLE / { found = 1 } END { exit !found }'; then
  echo "Database dump has no tables; initialize the wiki before backing it up." >&2
  exit 1
fi

if [[ "$(date -u +%u)" == 7 ]]; then
  cp "$temporary/dump.sql.gz" "$temporary/weekly.sql.gz"
  mv "$temporary/weekly.sql.gz" "$BACKUP_DIR/weekly/mirklurk-$today.sql.gz"
fi
mv "$temporary/dump.sql.gz" "$BACKUP_DIR/daily/mirklurk-$today.sql.gz"

find "$BACKUP_DIR/daily" -maxdepth 1 -type f -name 'mirklurk-*.sql.gz' -mtime +6 -delete
find "$BACKUP_DIR/weekly" -maxdepth 1 -type f -name 'mirklurk-*.sql.gz' -mtime +27 -delete
touch "$BACKUP_DIR/.last-success"
rm -f "$BACKUP_DIR/.last-failure"
echo "MirkLurk database backup complete: daily/mirklurk-$today.sql.gz"
