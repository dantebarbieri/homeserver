{ pkgs, ... }:

{
  systemd.services.server-atlas-collector = {
    description = "Server Atlas read-only hardware telemetry collector";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    path = with pkgs; [ util-linux smartmontools ipmitool lvm2 coreutils "/run/current-system/sw" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.python3}/bin/python3 ${../../hardware-map/server/collector.py} --state-dir /var/lib/server-atlas";
      Restart = "on-failure";
      RestartSec = 10;
      Group = "nogroup";
      StateDirectory = "server-atlas";
      StateDirectoryMode = "0750";
      UMask = "0027";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectControlGroups = true;
      ReadOnlyPaths = [ "/dev" "/proc" "/sys" ];
      RestrictAddressFamilies = [ "AF_UNIX" "AF_NETLINK" ];
      TimeoutStopSec = 15;
    };
  };
}
