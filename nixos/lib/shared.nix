# Values shared by several modules: the ntfy endpoint, alert scripts and the
# MirkLurk deployment-hold condition. Import with { inherit config pkgs; }.
{ config, pkgs }:

let
  # ─── ntfy push-notification infrastructure ───────────────────────────────
  # Your self-hosted ntfy instance (Docker container "ntfy").
  # Subscribe on your phone — see NTFY-PHONE-SETUP.md
  ntfyUrl   = "https://ntfy.danteb.com";
  ntfyTopic = "homeserver-alerts";
  mirklurkDeploymentCondition = "!/var/lib/mirklurk-upload-deployment/hold";

  # General-purpose CLI helper (available in $PATH as `ntfy-notify`)
  #   Usage: ntfy-notify "Title" "Message body" [priority] [tags]
  ntfyNotify = pkgs.writeShellScriptBin "ntfy-notify" ''
    TITLE="''${1:-Homeserver Alert}"
    MESSAGE="''${2:-No details provided}"
    PRIORITY="''${3:-default}"
    TAGS="''${4:-}"
    ${pkgs.curl}/bin/curl -s \
      -H "Title: $TITLE" \
      -H "Priority: $PRIORITY" \
      -H "Tags: $TAGS" \
      -d "$MESSAGE" \
      "${ntfyUrl}/${ntfyTopic}"
  '';

  # smartd alert handler (called via -M exec; receives SMARTD_* env vars)
  smartdAlert = pkgs.writeShellScript "smartd-ntfy" ''
    ${pkgs.curl}/bin/curl -s \
      -H "Title: SMART: $SMARTD_FAILTYPE on ${config.networking.hostName}" \
      -H "Priority: high" \
      -H "Tags: warning,computer" \
      -d "Device: $SMARTD_DEVICE — Type: $SMARTD_DEVICETYPE — $SMARTD_MESSAGE" \
      "${ntfyUrl}/${ntfyTopic}"
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

    ${pkgs.curl}/bin/curl -s \
      -H "Title: RAID $EVENT on ${config.networking.hostName}" \
      -H "Priority: $PRIORITY" \
      -H "Tags: $TAGS" \
      -d "Array: $MD_DEVICE | Component: $COMPONENT" \
      "${ntfyUrl}/${ntfyTopic}"
  '';
in
{
  inherit ntfyUrl ntfyTopic mirklurkDeploymentCondition ntfyNotify smartdAlert mdadmAlert;
}
