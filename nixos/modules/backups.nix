# Database dumps and encrypted offsite sync.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyNotify mirklurkDeploymentCondition;
in
{
  # ── Backup automation (database dumps + Vaultwarden + rclone offsite) ─────

  systemd.services.postgres-backup = {
    description = "Dump databases and copy Vaultwarden data";
    after = [ "docker.service" "network-online.target" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker coreutils gzip gnutar findutils ntfyNotify ];
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    script = ''
      set -uo pipefail

      BACKUP_ROOT="/data/automated-backups"
      PG_DIR="$BACKUP_ROOT/postgres"
      MYSQL_DIR="$BACKUP_ROOT/mariadb"
      VW_DIR="$BACKUP_ROOT/vaultwarden"
      DATE=$(date +%Y-%m-%d)
      DOW=$(date +%u)  # 1=Monday, 7=Sunday

      mkdir -p \
        "$PG_DIR/daily" "$PG_DIR/weekly" \
        "$MYSQL_DIR/daily" "$MYSQL_DIR/weekly" \
        "$VW_DIR"

      FAILED=""
      SUCCEEDED=""

      # dump CONTAINER FILE COMMAND...: writes COMMAND's output to FILE
      # gzipped and sets RESULT to ok or the reason it failed. A database
      # that has just started can refuse connections for a few seconds, so a
      # failed or empty dump is retried; a stopped container is reported as
      # such rather than as a dump failure.
      dump() {
        local container=$1 file=$2 attempt state
        shift 2
        for attempt in 1 2 3; do
          state=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null) ||
            state=missing
          if [ "$state" != running ]; then
            RESULT="not running: $state"
          elif "$@" | gzip > "$file"; then
            # gzip header alone is ~20 bytes
            if [ "$(stat -c%s "$file" 2>/dev/null || echo 0)" -gt 100 ]; then
              RESULT=ok
              return 0
            fi
            RESULT=empty
          else
            RESULT="dump failed"
          fi
          rm -f "$file"
          if [ "$attempt" -lt 3 ]; then
            echo "$container: $RESULT (attempt $attempt of 3), retrying in 30 s" >&2
            sleep 30
          fi
        done
        return 0
      }

      # Format: "container:user:database"
      DATABASES="
        immich_postgres:postgres:immich
        authelia_postgres:authelia:authelia
        synapse_postgres:synapse:synapse
        nextcloud_postgres:nextcloud:nextcloud
        forgejo_postgres:forgejo:forgejo
        suwayomi_postgres:suwayomi:suwayomi_db
      "

      for entry in $DATABASES; do
        CONTAINER=$(echo "$entry" | cut -d: -f1)
        USER=$(echo "$entry" | cut -d: -f2)
        DB=$(echo "$entry" | cut -d: -f3)
        DUMP_FILE="$PG_DIR/daily/''${CONTAINER}-''${DATE}.sql.gz"

        dump "$CONTAINER" "$DUMP_FILE" docker exec "$CONTAINER" pg_dump -U "$USER" "$DB"
        if [ "$RESULT" = ok ]; then
          SUCCEEDED="$SUCCEEDED $CONTAINER"
        else
          FAILED="$FAILED $CONTAINER($RESULT)"
        fi
      done

      # RomM MariaDB dump. Read credentials from the container environment so
      # they never need to be duplicated in the NixOS configuration.
      MYSQL_DUMP="$MYSQL_DIR/daily/romm-db-''${DATE}.sql.gz"
      dump romm-db "$MYSQL_DUMP" docker exec romm-db sh -c \
        'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump --single-transaction --quick --lock-tables=false -u root "$MARIADB_DATABASE"'
      if [ "$RESULT" = ok ]; then
        SUCCEEDED="$SUCCEEDED romm-db"
      else
        FAILED="$FAILED romm-db($RESULT)"
      fi

      # Weekly rotation: copy Sunday's dumps
      if [ "$DOW" = "7" ]; then
        for dir in "$PG_DIR" "$MYSQL_DIR"; do
          for f in "$dir/daily/"*-"$DATE".sql.gz; do
            [ -f "$f" ] && cp "$f" "$dir/weekly/"
          done
        done
      fi

      # Retention: 7 daily, 4 weekly
      for dir in "$PG_DIR" "$MYSQL_DIR"; do
        find "$dir/daily" -name "*.sql.gz" -mtime +7 -delete
        find "$dir/weekly" -name "*.sql.gz" -mtime +28 -delete
      done

      # Vaultwarden backup (SQLite WAL-mode safe for file copy)
      VW_FAILED=""
      if docker cp vaultwarden:/data/. "$VW_DIR/"; then
        VW_STATUS="ok"
      else
        VW_FAILED="vaultwarden"
      fi

      # ntfy notification
      SUCCEEDED=$(echo "$SUCCEEDED" | xargs)
      FAILED=$(echo "$FAILED $VW_FAILED" | xargs)

      # Silent on success — only alert on per-database / Vaultwarden failures.
      # Timeouts / SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        ntfy-notify "Backup FAILED on ${config.networking.hostName}" \
          "FAILED: $FAILED | Succeeded: $SUCCEEDED" high "warning,floppy_disk" ||
          echo "Backup failure alert was not delivered" >&2
        exit 1
      fi
    '';
  };

  systemd.timers.postgres-backup = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 03:00:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  systemd.services.rclone-offsite-daily = {
    description = "Daily rclone sync of backups, configs, and active data to Google Drive";
    after = [ "postgres-backup.service" "mirklurk-snapshot.service" "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      TimeoutStartSec = "8h";
    };
    environment.RCLONE_CONFIG = "/root/.config/rclone/rclone.conf";
    path = with pkgs; [ rclone rsync coreutils ntfyNotify ];
    script = ''
      set -uo pipefail

      REMOTE="gdrive-crypt:homeserver-backups"
      FAILED=""

      # Database dumps + Vaultwarden
      if ! rclone sync /data/automated-backups/ "$REMOTE/automated-backups/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED automated-backups"
      fi

      # Nextcloud user files
      if ! rclone sync /data/nextcloud/ "$REMOTE/nextcloud/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED nextcloud"
      fi

      # Compose .env — the only copy of ~150 credentials, and it lives on the
      # boot drive outside every other backup target below (/srv/homeserver is
      # a git clone, and .env is gitignored by design). Losing the boot drive
      # without this means rotating every secret by hand. The remote is a
      # crypt remote, so it is encrypted before it leaves the host.
      if ! rclone copy /srv/homeserver/docker/.env "$REMOTE/secrets/" \
          --log-level NOTICE 2>&1; then
        FAILED="$FAILED compose-env"
      fi

      # Selective /srv/docker/data (service configs and non-regenerable app data).
      # Live files change and vanish while a slow upload runs, and any such
      # error makes rclone rerun the whole sync (up to 3x) and skip remote
      # deletions, which pushed this job past its timeout. So it is first
      # mirrored to a local staging copy (minutes; rsync exit 24 means a file
      # vanished mid-copy, which is harmless), and rclone uploads from that.
      # Also skipped: AdGuard's DNS query log (~4 GB rewritten daily, plus a
      # ~9 GB rotation), *arr crash-report spools, text logs and log DBs,
      # slskd's event and search history, Suwayomi's browser cache, and
      # SQLite -shm indexes (rebuilt on open; databases and -wal are kept).
      # Nextcloud's code ships in its image, but config/ (instance secrets)
      # and themes/ are what its backup docs say to keep (rsync filters are
      # first-match, so the includes go first).
      STAGE=/data/offsite-staging/docker-data
      mkdir -p "$STAGE" && chmod 700 /data/offsite-staging
      rsync -a --delete --delete-excluded --no-specials --no-devices \
          --include "/nextcloud/html/config/***" \
          --include "/nextcloud/html/themes/***" \
          --exclude "/nextcloud/html/*" \
          --exclude "/plex/" \
          --exclude "/jellyfin/" \
          --exclude "/romm/resources/" \
          --exclude "/satisfactory-server/" \
          --exclude "/syncthing/" \
          --exclude "/tdarr/logs/" \
          --exclude "/nginxproxymanager/data/logs/" \
          --exclude "/prometheus/" \
          --exclude "/loki/" \
          --exclude "/alloy/" \
          --exclude "/mirklurk/backups/.mirklurk-*/" \
          --exclude "/mirklurk/backups/.mirklurk-snapshot-sql-*.sql.gz" \
          --exclude "/mirklurk/backup-control/" \
          --exclude "/adguardhome/workdir/data/querylog.json*" \
          --exclude "/*/config/Sentry/" \
          --exclude "/*/config/logs/" \
          --exclude "/*/config/logs.db*" \
          --exclude "/slskd/data/events.db*" \
          --exclude "/slskd/data/search.db*" \
          --exclude "/suwayomi/config/cache/" \
          --exclude "*-shm" \
          /srv/docker/data/ "$STAGE/" 2>&1
      RC=$?
      if [ "$RC" -ne 0 ] && [ "$RC" -ne 24 ]; then
        FAILED="$FAILED docker-data-staging(rsync=$RC)"
      fi
      # --fast-list matters: on this crypt-over-Drive remote, one subtree
      # (27k objects) lists in 31s with it and over 3 min without. Remote
      # deletions cost one Drive API call per file and directory, after the
      # uploads, so dropping a big tree from the backup can take hours; purge
      # it server-side first (rclone purge is one call on Drive). The
      # periodic stats line shows which phase a long run is in.
      if ! rclone sync "$STAGE/" "$REMOTE/docker-data/" \
          --fast-list --transfers 4 --checkers 8 --log-level NOTICE \
          --stats 30m --stats-one-line --stats-log-level NOTICE 2>&1; then
        FAILED="$FAILED docker-data"
      fi

      FAILED=$(echo "$FAILED" | xargs)

      # Silent on success — only alert on rclone-level failures. Timeouts /
      # SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        ntfy-notify "Daily offsite sync FAILED on ${config.networking.hostName}" \
          "Failed sync targets: $FAILED" high "warning,cloud" ||
          echo "Offsite failure alert was not delivered" >&2
        exit 1
      fi
    '';
  };

  systemd.timers.rclone-offsite-daily = {
    wantedBy = [ "timers.target" ];
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    timerConfig = {
      OnCalendar = "*-*-* 03:30:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  systemd.services.rclone-offsite-weekly = {
    description = "Weekly rclone sync of large static media to Google Drive";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      TimeoutStartSec = "24h";
    };
    environment.RCLONE_CONFIG = "/root/.config/rclone/rclone.conf";
    path = with pkgs; [ rclone coreutils ntfyNotify ];
    script = ''
      set -uo pipefail

      REMOTE="gdrive-crypt:homeserver-backups"
      FAILED=""

      # Home videos (374 GB, rare changes). Rename tracking turns local moves
      # within this tree into server-side moves instead of re-uploads; crypt
      # remotes have no hashes, so match on modtime+leaf.
      if ! rclone sync /data/shared/media/other/ "$REMOTE/media/home-videos/" \
          --track-renames --track-renames-strategy modtime,leaf \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED home-videos"
      fi

      # DV tape originals (~180 GB, static). Kept outside the Plex/Jellyfin
      # library roots so the DV MKVs (unplayable by Plex 1.43.x's broken
      # dvvideo codec) don't get indexed; the converted H.264 versions live
      # in .../other/Segu/Tape */. See docker/scripts/transcode-dv-tapes.sh.
      if ! rclone sync /data/Segu-DV-originals/ "$REMOTE/media/segu-dv-originals/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED segu-dv-originals"
      fi

      # Videotape digitization (179 GB, static)
      if ! rclone sync /data/Segu-raw/ "$REMOTE/media/segu-raw/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED segu-raw"
      fi

      # FCP edits + travel vlog (25 GB, static)
      if ! rclone sync /data/backups/ "$REMOTE/media/fcp-backups/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED fcp-backups"
      fi

      FAILED=$(echo "$FAILED" | xargs)

      # Silent on success — only alert on rclone-level failures. Timeouts /
      # SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        ntfy-notify "Weekly offsite sync FAILED on ${config.networking.hostName}" \
          "Failed sync targets: $FAILED" high "warning,cloud" ||
          echo "Offsite failure alert was not delivered" >&2
        exit 1
      fi
    '';
  };

  systemd.timers.rclone-offsite-weekly = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "Sun *-*-* 05:00:00";
      Persistent = true;
      RandomizedDelaySec = "15m";
    };
  };
}
