# Operator-requested reboots wait outside the SSH session, never on a timer.
{ config, lib, pkgs, ... }:

let
  jobs = [
    "postgres-backup"
    "rclone-offsite-daily"
    "rclone-offsite-weekly"
    "docker-compose-update"
    "docker-socket-consumers"
    "nixos-upgrade"
    "mdadm-scrub"
    "mirklurk-snapshot"
    "mirklurk-auto-update"
    "mirklurk-backup-check"
    "mirklurk-sitemap"
  ];
  jobConfig = pkgs.writeText "safe-reboot-jobs.json" (builtins.toJSON {
    services = map (name: "${name}.service") jobs;
    timers = map (name: "${name}.timer")
      (builtins.filter (name: builtins.hasAttr name config.systemd.timers) jobs);
  });
  command = pkgs.writeShellApplication {
    name = "safe-reboot";
    runtimeInputs = [ pkgs.systemd pkgs.docker ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${../safe-reboot.py} ${jobConfig} "$@"
    '';
  };
in
{
  environment.systemPackages = [ command ];

  systemd.services = lib.genAttrs jobs (_: {
    # Adding the guard must not interrupt an already-running backup on switch.
    restartIfChanged = false;
    unitConfig.ConditionPathExists = [ "!/run/safe-reboot/pending" ];
  }) // {
    safe-reboot = {
      description = "Wait for homeserver backups and maintenance, then reboot";
      restartIfChanged = false;
      # On shutdown Docker must finish BEFORE we release the wiki backup lock.
      before = [ "docker.service" ];
      unitConfig.OnFailure = "ntfy-failure@%n.service";
      serviceConfig = {
        Type = "exec";
        ExecStart = "${command}/bin/safe-reboot --worker";
        ExecStopPost = "${command}/bin/safe-reboot --cleanup";
        RuntimeDirectory = "safe-reboot";
        RuntimeDirectoryMode = "0700";
        # Keep the timer recovery record if ExecStopPost itself fails.
        RuntimeDirectoryPreserve = true;
        TimeoutStopSec = "60s";
        UMask = "0077";
      };
    };
  };
}
