# ntfy reminder that the running system is behind what the nightly upgrade
# staged. nixos-upgrade (auto-upgrade.nix) only runs `nixos-rebuild boot` and
# never reboots, so kernel, NVIDIA and userland updates wait for a person.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic;
  # The upgrade stages something almost every night, so stay quiet for this
  # long after a reboot instead of nagging about every generation.
  staleDays = 7;
  rebootNeeded = pkgs.writeShellScriptBin "reboot-needed" ''
    exec ${pkgs.python3}/bin/python3 ${../reboot-needed.py} "$@"
  '';
in
{
  environment.systemPackages = [ rebootNeeded ];

  systemd.services.reboot-reminder = {
    description = "Remind via ntfy to reboot into staged NixOS updates";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig.Type = "oneshot";
    path = with pkgs; [ coreutils gawk curl rebootNeeded ];
    script = ''
      uptime_file=/proc/uptime
      md_sync=/sys/block/md0/md/sync_action
      stale_days=${toString staleDays}

      days=$(awk '{ print int($1 / 86400) }' "$uptime_file")
      if [ "$days" -lt "$stale_days" ]; then
        echo "Up $days days (< $stale_days); nothing to do"
        exit 0
      fi

      if message=$(reboot-needed); then
        echo "$message"
        exit 0
      else
        status=$?
        if [ "$status" -ne 1 ]; then
          echo "Cannot determine whether a reboot is needed (exit $status)" >&2
          exit "$status"
        fi
      fi

      # A scrub or rebuild is not verified if a reboot cuts it short (see the
      # README), so hold the reminder until the array is idle.
      if [ -r "$md_sync" ]; then
        action=$(cat "$md_sync")
        if [ "$action" != idle ]; then
          echo "RAID md0 is running '$action'; not reminding until it is idle"
          exit 0
        fi
      fi

      curl --fail-with-body --show-error --silent --max-time 30 \
        -H "Title: Reboot needed on ${config.networking.hostName}" \
        -H "Tags: arrows_counterclockwise,computer" \
        -d "$message Up $days days; this reminder does not queue a reboot." \
        "${ntfyUrl}/${ntfyTopic}"
    '';
  };

  # Not Persistent: a missed run needs no catching up, because a reboot is
  # exactly what the reminder asks for.
  systemd.timers.reboot-reminder = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 10:00:00";
      RandomizedDelaySec = "10m";
    };
  };
}
