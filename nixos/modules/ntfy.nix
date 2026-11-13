# ntfy failure handler shared by monitoring units. The ntfy-notify CLI is
# installed from modules/shell.nix.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic ntfySpool ntfyCurl ntfyNotify;
  userSpool = "${config.users.users.danteb.home}/.local/state/ntfy-spool";
  flushSpool = ''
    spool="$1"
    find "$spool" -mindepth 1 -maxdepth 1 -name '.new.*' -mmin +60 -exec rm -rf {} +
    for entry in "$spool"/*.alert; do
      [ -d "$entry" ] || continue
      if ! title=$(cat "$entry/title") ||
         ! message=$(cat "$entry/message") ||
         ! priority=$(cat "$entry/priority") ||
         ! tags=$(cat "$entry/tags") ||
         ! queued=$(cat "$entry/queued"); then
        echo "Cannot read queued ntfy alert in $entry; retaining it" >&2
        continue
      fi
      if ntfy_curl --fail --silent --show-error --max-time 20 \
          -H "Title: $title (delayed)" \
          -H "Priority: $priority" \
          -H "Tags: $tags" \
          --data-raw "$message"$'\n\n'"Queued at $queued while ntfy was unreachable." \
          "${ntfyUrl}/${ntfyTopic}" > /dev/null; then
        rm -rf "$entry"
      else
        echo "ntfy is still unreachable; queued alerts stay in $spool" >&2
        break
      fi
    done
  '';
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
  # User-owned entries are read and sent only after dropping root privileges.
  systemd.tmpfiles.rules = [ "d ${ntfySpool} 0700 root root -" ];

  systemd.services.ntfy-spool-flush = {
    description = "Deliver ntfy alerts queued while ntfy was unreachable";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = with pkgs; [ curl coreutils findutils ];
    serviceConfig.Type = "oneshot";
    script = ''
      ${ntfyCurl}
      flush_spool() {
        ${flushSpool}
      }
      flush_spool ${ntfySpool}
      if [ -d ${userSpool} ]; then
        ${pkgs.lib.getBin pkgs.util-linux}/bin/runuser -u danteb -- ${pkgs.bash}/bin/bash \
          -s -- ${userSpool} <<'NTFY_FLUSH'
      ${ntfyCurl}
      ${flushSpool}
      NTFY_FLUSH
      fi
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
