# ntfy failure handler shared by monitoring units. The ntfy-notify CLI is
# installed from modules/shell.nix.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic ntfySpool ntfyNotify;
in
{
  # ── Generic ntfy failure handler ──────────────────────────────────────────
  # Wired via `unitConfig.OnFailure = "ntfy-failure@%n.service"` on units
  # whose normal failure path (an in-script curl) won't fire — e.g. when the
  # service is SIGTERM'd by TimeoutStartSec= or OOM-killed. Without this,
  # a timeout looks identical to a clean run from ntfy's perspective.
  # ntfy-notify queues the alert if ntfy itself is down.
  systemd.services."ntfy-failure@" = {
    description = "ntfy alert for failed unit %i";
    scriptArgs = "%i";
    serviceConfig.Type = "oneshot";
    script = ''
      UNIT="$1"
      ${ntfyNotify}/bin/ntfy-notify \
        "$UNIT FAILED on ${config.networking.hostName}" \
        "systemd unit $UNIT exited abnormally (timeout, OOM, or non-zero exit). Inspect: journalctl -u $UNIT" \
        high "warning,floppy_disk"
    '';
  };

  # ── Queued alert delivery ─────────────────────────────────────────────────
  # Delivers what ntfy-notify queued while ntfy was unreachable, oldest first.
  # It succeeds quietly while ntfy is still down: there is nothing to alert
  # through, and the queue keeps the alerts until it is back.
  systemd.tmpfiles.rules = [ "d ${ntfySpool} 0700 root root -" ];

  systemd.services.ntfy-spool-flush = {
    description = "Deliver ntfy alerts queued while ntfy was unreachable";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.ConditionDirectoryNotEmpty = ntfySpool;
    path = with pkgs; [ curl coreutils findutils ];
    serviceConfig.Type = "oneshot";
    script = ''
      # Entries an interrupted ntfy-notify never finished writing.
      find ${ntfySpool} -mindepth 1 -maxdepth 1 -name '.new.*' -mmin +60 -exec rm -rf {} +
      for entry in ${ntfySpool}/*.alert; do
        [ -d "$entry" ] || continue
        title=$(cat "$entry/title" 2>/dev/null || echo "Homeserver Alert")
        message=$(cat "$entry/message" 2>/dev/null || echo "No details provided")
        priority=$(cat "$entry/priority" 2>/dev/null || echo default)
        tags=$(cat "$entry/tags" 2>/dev/null || true)
        queued=$(cat "$entry/queued" 2>/dev/null || echo "an unknown time")
        if curl --fail --silent --show-error --max-time 20 \
            -H "Title: $title (delayed)" \
            -H "Priority: $priority" \
            -H "Tags: $tags" \
            --data-raw "$message"$'\n\n'"Queued at $queued while ntfy was unreachable." \
            "${ntfyUrl}/${ntfyTopic}" > /dev/null; then
          rm -rf "$entry"
        else
          echo "ntfy is still unreachable; queued alerts stay in ${ntfySpool}" >&2
          exit 0
        fi
      done
    '';
  };

  systemd.timers.ntfy-spool-flush = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2min";
      OnCalendar = "*:0/5";
    };
  };
}
