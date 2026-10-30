# Database dumps and encrypted offsite sync.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic mirklurkDeploymentCondition;
in
{
  # ── Backup automation (database dumps + Vaultwarden + rclone offsite) ─────

  systemd.services.postgres-backup = {
    description = "Dump databases and copy Vaultwarden data";
    after = [ "docker.service" "network-online.target" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker coreutils gzip curl gnutar findutils ];
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

        if docker exec "$CONTAINER" pg_dump -U "$USER" "$DB" 2>/dev/null | gzip > "$DUMP_FILE"; then
          # Verify non-empty (gzip header alone is ~20 bytes)
          if [ "$(stat -c%s "$DUMP_FILE" 2>/dev/null || echo 0)" -gt 100 ]; then
            SUCCEEDED="$SUCCEEDED $CONTAINER"
          else
            FAILED="$FAILED $CONTAINER(empty)"
            rm -f "$DUMP_FILE"
          fi
        else
          FAILED="$FAILED $CONTAINER"
          rm -f "$DUMP_FILE"
        fi
      done

      # RomM MariaDB dump. Read credentials from the container environment so
      # they never need to be duplicated in the NixOS configuration.
      MYSQL_DUMP="$MYSQL_DIR/daily/romm-db-''${DATE}.sql.gz"
      if docker exec romm-db sh -c \
          'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump --single-transaction --quick --lock-tables=false -u root "$MARIADB_DATABASE"' \
          2>/dev/null | gzip > "$MYSQL_DUMP"; then
        if [ "$(stat -c%s "$MYSQL_DUMP" 2>/dev/null || echo 0)" -gt 100 ]; then
          SUCCEEDED="$SUCCEEDED romm-db"
        else
          FAILED="$FAILED romm-db(empty)"
          rm -f "$MYSQL_DUMP"
        fi
      else
        FAILED="$FAILED romm-db"
        rm -f "$MYSQL_DUMP"
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
      if docker cp vaultwarden:/data/. "$VW_DIR/" 2>/dev/null; then
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
        curl -s \
          -H "Title: Backup FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,floppy_disk" \
          -d "FAILED: $FAILED | Succeeded: $SUCCEEDED" \
          "${ntfyUrl}/${ntfyTopic}"
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
    path = with pkgs; [ rclone curl coreutils ];
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

      # Selective /srv/docker/data (service configs and non-regenerable app data)
      if ! rclone sync /srv/docker/data/ "$REMOTE/docker-data/" \
          --exclude "plex/**" \
          --exclude "jellyfin/**" \
          --exclude "romm/resources/**" \
          --exclude "satisfactory-server/**" \
          --exclude "syncthing/**" \
          --exclude "tdarr/logs/**" \
          --exclude "nextcloud/html/**" \
          --exclude "nginxproxymanager/data/logs/**" \
          --exclude "prometheus/**" \
          --exclude "loki/**" \
          --exclude "alloy/**" \
          --exclude "mirklurk/backups/.mirklurk-*/**" \
          --exclude "mirklurk/backups/.mirklurk-snapshot-sql-*.sql.gz" \
          --exclude "mirklurk/backup-control/**" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED docker-data"
      fi

      FAILED=$(echo "$FAILED" | xargs)

      # Silent on success — only alert on rclone-level failures. Timeouts /
      # SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        curl -s \
          -H "Title: Daily offsite sync FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,cloud" \
          -d "Failed sync targets: $FAILED" \
          "${ntfyUrl}/${ntfyTopic}"
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
    path = with pkgs; [ rclone curl coreutils ];
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
        curl -s \
          -H "Title: Weekly offsite sync FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,cloud" \
          -d "Failed sync targets: $FAILED" \
          "${ntfyUrl}/${ntfyTopic}"
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
