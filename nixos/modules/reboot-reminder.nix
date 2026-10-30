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
in
{
  systemd.services.reboot-reminder = {
    description = "Remind via ntfy to reboot into staged NixOS updates";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig.Type = "oneshot";
    path = with pkgs; [ coreutils gawk curl ];
    script = ''
      booted=/run/booted-system
      current=/run/current-system
      staged=/nix/var/nix/profiles/system
      uptime_file=/proc/uptime
      md_sync=/sys/block/md0/md/sync_action
      stale_days=${toString staleDays}

      days=$(awk '{ print int($1 / 86400) }' "$uptime_file")
      if [ "$days" -lt "$stale_days" ]; then
        echo "Up $days days (< $stale_days); nothing to do"
        exit 0
      fi

      # Same comparison as nixpkgs' allowReboot: a different kernel, initrd or
      # module tree (which carries the NVIDIA driver) cannot load without a reboot.
      kernel_changed=0
      for part in kernel initrd kernel-modules; do
        if [ "$(readlink "$booted/$part")" != "$(readlink "$staged/$part")" ]; then
          kernel_changed=1
        fi
      done

      if [ "$kernel_changed" -eq 1 ]; then
        running=$(ls -1 "$booted/kernel-modules/lib/modules" 2>/dev/null | head -n 1 || true)
        next=$(ls -1 "$staged/kernel-modules/lib/modules" 2>/dev/null | head -n 1 || true)
        if [ "$running" = "$next" ]; then
          message="Kernel modules or initrd changed on $running (e.g. an NVIDIA driver update)."
        else
          message="Kernel update staged: running $running, next boot $next."
        fi
      elif [ "$(readlink -f "$current")" != "$(readlink -f "$staged")" ]; then
        message="OS updates are staged but not running yet."
      else
        echo "Running system matches the staged generation; nothing to do"
        exit 0
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
        -H "Title: Reboot pending on ${config.networking.hostName}" \
        -H "Tags: arrows_counterclockwise,computer" \
        -d "$message Up $days days; reboot when convenient." \
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
