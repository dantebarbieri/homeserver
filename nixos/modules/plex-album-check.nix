# Nightly, read-only check that Plex has not merged several album folders into
# one album. A merged album shows mixed art and track lists in Plexamp and
# survives retags; docker/docs/MUSIC.md ("Fixing merged Plex albums") has the
# cause and the repair. This only reads Plex's database and sends ntfy: it never
# changes Plex, Lidarr or a media file.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyNotify;
  # A merge stays until someone repairs it, so after the first alert repeat it
  # this often instead of every night.
  remindDays = 7;
  # ntfy bodies are capped at 4 KB: list this many albums and count the rest.
  maxListed = 12;
in
{
  systemd.services.plex-album-check = {
    description = "Alert via ntfy when Plex merges several album folders into one album";
    after = [ "docker.service" "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig = {
      Type = "oneshot";
      # Remembers which merges were already reported.
      StateDirectory = "plex-album-check";
    };
    path = with pkgs; [ coreutils curl docker gawk gnugrep jq ];
    script = ''
      set -o pipefail

      db='/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db'
      state_dir=/var/lib/plex-album-check
      remind_days=${toString remindDays}
      max_listed=${toString maxListed}
      known="$state_dir/known"
      alerted="$state_dir/alerted"

      # One read-only SELECT of every track in the music libraries (section type
      # 8). -bail turns a SQL error into a failed unit instead of partial output.
      rows=$(docker exec -i plex '/usr/lib/plexmediaserver/Plex SQLite' \
        -bail -readonly -json -cmd '.timeout 30000' "$db" <<'SQL'
      SELECT a.id AS album_id, ar.title AS artist, a.title AS album, mp.file AS file
      FROM media_parts mp
      JOIN media_items me ON me.id = mp.media_item_id
      JOIN metadata_items t ON t.id = me.metadata_item_id AND t.metadata_type = 10
      JOIN metadata_items a ON a.id = t.parent_id
      LEFT JOIN metadata_items ar ON ar.id = a.parent_id
      JOIN library_sections ls ON ls.id = t.library_section_id AND ls.section_type = 8
      WHERE mp.deleted_at IS NULL AND me.deleted_at IS NULL AND t.deleted_at IS NULL;
      SQL
      )

      # An empty result is not a clean library: the JSON mode prints nothing
      # for zero rows, so it would hide a moved library or a wrong database path.
      if [ -z "$rows" ]; then
        echo "Plex returned no music tracks; check the music library and database path" >&2
        exit 1
      fi

      # One line per album whose tracks sit in more than one folder: name,
      # folder count, track count. Lidarr's multi-disc layout is one folder per
      # album, but a trailing CD1 or Disc 2 folder still belongs to its album.
      offenders=$(jq -r '
        def disc: test("^(cd|dis[ck]|vinyl|digital media|lp|dvd|sacd)[ ._-]*[0-9]+([ ._-].*)?$"; "i");
        def folder:
          sub("/[^/]*$"; "")
          | if (split("/") | last // "" | disc) then sub("/[^/]*$"; "") else . end;
        group_by(.album_id)
        | map({
            name: "\(.[0].artist // "") - \(.[0].album)",
            folders: (map(.file | folder) | unique | length),
            tracks: length
          })
        | map(select(.folders > 1))
        | sort_by(.name)
        | .[]
        | [.name, .folders, .tracks]
        | @tsv
      ' <<< "$rows")

      if [ -z "$offenders" ]; then
        echo "No Plex album spans more than one folder"
        rm -f "$known" "$alerted"
        exit 0
      fi

      current=$(cut -f1 <<< "$offenders" | LC_ALL=C sort -u)
      if [ -f "$known" ]; then
        new=$(grep -Fvxf "$known" <<< "$current" || true)
      else
        new=$current
      fi
      last=$(cat "$alerted" 2>/dev/null || echo 0)
      case "$last" in
        "" | *[!0-9]*) last=0 ;;
      esac
      now=$(date +%s)

      if [ -n "$new" ]; then
        only=$new
        heading="Plex merged several album folders into one album (mixed art and track lists in Plexamp):"
      elif [ $((now - last)) -ge $((remind_days * 86400)) ]; then
        only=$current
        heading="Still merged in Plex (not repaired yet):"
      else
        echo "Already reported: $(wc -l <<< "$current") merged album(s)"
        printf '%s\n' "$current" > "$known"
        exit 0
      fi

      # Lines of "offenders" whose name is in $1, capped at max_listed. The
      # names go through ENVIRON, not -v, which would process backslashes.
      describe() {
        ONLY=$1 MAX=$max_listed awk '
          BEGIN {
            FS = "\t"
            n = split(ENVIRON["ONLY"], names, "\n")
            for (i = 1; i <= n; i++) wanted[names[i]] = 1
            max = ENVIRON["MAX"] + 0
          }
          ($1 in wanted) {
            shown++
            if (shown <= max) printf "- %s (%d folders, %d tracks)\n", $1, $2, $3
          }
          END { if (shown > max) printf "...and %d more\n", shown - max }
        ' <<< "$offenders"
      }

      message=$(printf '%s\n' "$heading" "$(describe "$only")" "" \
        'Repair: docker/docs/MUSIC.md, section "Fixing merged Plex albums".')
      echo "$message"

      # Record the report only once it was delivered or durably queued.
      ${ntfyNotify}/bin/ntfy-notify \
        "Merged Plex albums on ${config.networking.hostName}" \
        "$message" default "warning,musical_note" || exit $?
      printf '%s\n' "$current" > "$known"
      echo "$now" > "$alerted"
    '';
  };

  # Not Persistent: a missed night is caught by the next one, and a run at boot
  # could race Plex starting.
  systemd.timers.plex-album-check = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 06:30:00";
      RandomizedDelaySec = "10m";
    };
  };
}
