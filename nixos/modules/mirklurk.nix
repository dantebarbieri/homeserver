# MirkLurk wiki maintenance: sitemap, auto-update, snapshots and backup checks.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    mirklurkDeploymentCondition;
in
{
  systemd.services.mirklurk-sitemap = {
    description = "Refresh and verify the public MirkLurk sitemap";
    after = [ "docker.service" "network-online.target" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker systemd ];
    serviceConfig = {
      Type = "oneshot";
      TimeoutStartSec = "10min";
    };
    script = ''
      ${pkgs.python3}/bin/python3 /srv/homeserver/docker/scripts/mirklurk-release.py refresh-sitemap
    '';
  };

  systemd.timers.mirklurk-sitemap = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 05:30:00";
      Persistent = true;
    };
  };

  # Unattended MirkLurk wiki base-image patching (docker/docs/MIRKLURK.md). The
  # generic updater above never touches the wiki frontend (Compose profile); this
  # unit builds mirklurk-wiki main and deploys it only when it differs from the
  # live revision by the MediaWiki 1.43 base line. It fails (ntfy) only for real
  # breakage or a stall, and holds itself after a failed activation.
  # The deployment-hold directory is permanent and world-readable so non-root
  # agents can check for a hold; only root may create or remove `hold` itself.
  systemd.tmpfiles.rules = [
    "d /var/lib/mirklurk-auto-update 2775 root docker - -"
    "d /var/lib/mirklurk-upload-deployment 0755 root root - -"
  ];

  systemd.services.mirklurk-auto-update = {
    description = "Build and deploy eligible MirkLurk wiki base-image updates";
    after = [ "docker.service" "network-online.target" "docker-compose-update.service" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    path = with pkgs; [ docker git coreutils ];
    serviceConfig = {
      Type = "oneshot";
      # Group docker (setgid state dir) can append history and clear the hold.
      UMask = "0002";
      TimeoutStartSec = "90min";
      TimeoutStopSec = "4min";
      KillMode = "mixed";
      Nice = 10;
    };
    script = ''
      exec ${pkgs.python3}/bin/python3 /srv/homeserver/docker/scripts/mirklurk-release.py auto-update
    '';
  };

  # After the 03:15 snapshot and the 04:00 updater; activation stays clear of the
  # hourly :45 backup check and the 05:30 sitemap refresh, which share its lock.
  systemd.timers.mirklurk-auto-update = {
    wantedBy = [ "timers.target" ];
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    timerConfig = {
      OnCalendar = "*-*-* 04:15:00";
      Persistent = true;
    };
  };

  systemd.services.mirklurk-snapshot = {
    description = "Consistent MirkLurk database and uploaded-file snapshot";
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    path = with pkgs; [ docker coreutils gnutar gzip ];
    serviceConfig = {
      Type = "oneshot";
      UMask = "0077";
      TimeoutStartSec = "30min";
      TimeoutStopSec = "4min";
      KillMode = "mixed";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    script = ''
      exec ${pkgs.python3}/bin/python3 /srv/homeserver/docker/scripts/mirklurk-release.py snapshot
    '';
  };

  systemd.timers.mirklurk-snapshot = {
    wantedBy = [ "timers.target" ];
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    timerConfig = {
      OnCalendar = "*-*-* 03:15:00";
      Persistent = true;
    };
  };

  systemd.services.mirklurk-backup-check = {
    description = "Check wiki backup freshness, storage space and inodes";
    after = [ "docker.service" "mirklurk-snapshot.service" ];
    requires = [ "docker.service" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    path = with pkgs; [ docker ];
    serviceConfig = {
      Type = "oneshot";
      TimeoutStartSec = "2min";
    };
    script = ''
      ${pkgs.python3}/bin/python3 /srv/homeserver/docker/scripts/mirklurk-release.py check-backups
    '';
  };

  systemd.timers.mirklurk-backup-check = {
    wantedBy = [ "timers.target" ];
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    timerConfig = {
      OnCalendar = "*-*-* *:45:00";
      Persistent = true;
    };
  };
}
