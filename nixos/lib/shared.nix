# Values shared by several modules: the ntfy endpoint, alert scripts and the
# MirkLurk deployment-hold condition. Import with { inherit config pkgs; }.
{ config, pkgs }:

let
  # ─── ntfy push-notification infrastructure ───────────────────────────────
  # Your self-hosted ntfy instance (Docker container "ntfy").
  # Subscribe on your phone — see NTFY-PHONE-SETUP.md
  ntfyUrl   = "https://ntfy.danteb.com";
  ntfyTopic = "homeserver-alerts";
  # ntfy runs in Docker, so it is down whenever Docker is. Root's alerts that
  # cannot be delivered wait here for ntfy-spool-flush (modules/ntfy.nix).
  ntfySpool = "/var/lib/ntfy-spool";
  mirklurkDeploymentCondition = "!/var/lib/mirklurk-upload-deployment/hold";

  # Read the publisher credential at runtime, never from the world-readable Nix store.
  ntfyCurl = builtins.readFile ../../docker/scripts/ntfy-curl.sh;

  # General-purpose CLI helper (available in $PATH as `ntfy-notify`)
  #   Usage: ntfy-notify "Title" "Message body" [priority] [tags]
  # Succeeds once the alert is delivered or queued; exits non-zero otherwise.
  ntfyNotify = pkgs.writeShellScriptBin "ntfy-notify" ''
    PATH=${pkgs.lib.makeBinPath [ pkgs.curl pkgs.coreutils pkgs.findutils ]}:$PATH
    TITLE="''${1:-Homeserver Alert}"
    MESSAGE="''${2:-No details provided}"
    PRIORITY="''${3:-default}"
    TAGS="''${4:-}"
    ${ntfyCurl}
    ntfy_curl --fail --silent --show-error --max-time 20 \
      --retry 2 --retry-delay 5 --retry-connrefused \
      -H "Title: $TITLE" \
      -H "Priority: $PRIORITY" \
      -H "Tags: $TAGS" \
      --data-raw "$MESSAGE" \
      "${ntfyUrl}/${ntfyTopic}" && exit 0
    status=$?
    if [ "$(id -u)" -eq 0 ]; then
      SPOOL=${ntfySpool}
    else
      SPOOL="$HOME/.local/state/ntfy-spool"
      umask 077
      mkdir -p "$SPOOL" || {
        echo "ntfy unreachable (curl exit $status); cannot create user spool" >&2
        exit "$status"
      }
      sync -d "$HOME" "$HOME/.local" "$HOME/.local/state" "$SPOOL" || {
        echo "ntfy unreachable (curl exit $status); cannot persist user spool" >&2
        exit "$status"
      }
    fi
    if [ -w "$SPOOL" ] &&
      entry=$(mktemp -d "$SPOOL/.new.XXXXXX"); then
      if printf '%s' "$TITLE" > "$entry/title" &&
        printf '%s' "$MESSAGE" > "$entry/message" &&
        printf '%s' "$PRIORITY" > "$entry/priority" &&
        printf '%s' "$TAGS" > "$entry/tags" &&
        date -u '+%Y-%m-%d %H:%M:%S UTC' > "$entry/queued" &&
        sync -d "$entry/title" "$entry/message" "$entry/priority" "$entry/tags" "$entry/queued" "$entry" &&
        mv "$entry" "$SPOOL/$(date -u +%Y%m%dT%H%M%S%N)-$$.alert" &&
        sync -d "$SPOOL"; then
        echo "ntfy unreachable (curl exit $status); alert queued in $SPOOL for redelivery" >&2
        exit 0
      fi
      rm -rf "$entry"
    fi
    echo "ntfy unreachable (curl exit $status); alert was not delivered" >&2
    exit "$status"
  '';

  # smartd alert handler (called via -M exec; receives SMARTD_* env vars)
  smartdAlert = pkgs.writeShellScript "smartd-ntfy" ''
    exec ${ntfyNotify}/bin/ntfy-notify \
      "SMART: $SMARTD_FAILTYPE on ${config.networking.hostName}" \
      "Device: $SMARTD_DEVICE — Type: $SMARTD_DEVICETYPE — $SMARTD_MESSAGE" \
      high "warning,computer"
  '';

  # mdadm event handler (PROGRAM directive; args: event device [component])
  mdadmAlert = pkgs.writeShellScript "mdadm-ntfy" ''
    EVENT="$1"
    MD_DEVICE="$2"
    COMPONENT="''${3:-none}"

    case "$EVENT" in
      Fail*|Degrade*|SparesMissing)
        PRIORITY="urgent"
        TAGS="rotating_light,computer"
        ;;
      Rebuild*|RebuildFinished)
        # Scheduled mdadm-scrub holds /run/mdadm-scrub for its full duration
        # (RuntimeDirectory=), so check/repair events are reliably suppressed.
        if [ -d /run/mdadm-scrub ]; then
          exit 0
        fi
        # Backup filter for manual `echo check/repair` outside the service.
        MD_NAME="''${MD_DEVICE##*/}"
        SYNC_ACTION=$(cat "/sys/block/$MD_NAME/md/sync_action" 2>/dev/null || echo "unknown")
        if [ "$SYNC_ACTION" = "check" ] || [ "$SYNC_ACTION" = "repair" ]; then
          exit 0
        fi
        PRIORITY="high"
        TAGS="construction,computer"
        ;;
      *)
        PRIORITY="default"
        TAGS="information_source,computer"
        ;;
    esac

    exec ${ntfyNotify}/bin/ntfy-notify \
      "RAID $EVENT on ${config.networking.hostName}" \
      "Array: $MD_DEVICE | Component: $COMPONENT" \
      "$PRIORITY" "$TAGS"
  '';
in
{
  inherit ntfyUrl ntfyTopic ntfySpool ntfyCurl mirklurkDeploymentCondition ntfyNotify smartdAlert mdadmAlert;
}
