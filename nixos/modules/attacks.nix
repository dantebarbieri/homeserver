{ config, lib, pkgs, ... }:

let
  capture = pkgs.runCommand "attacks-capture" { } ''
    mkdir -p "$out"
    cp ${../../attacks/capture.py} "$out/capture.py"
    cp ${../../attacks/events.py} "$out/events.py"
  '';
  intelligence = pkgs.runCommand "attacks-intelligence" { } ''
    mkdir -p "$out"
    cp ${../../attacks/update_intelligence.py} "$out/update_intelligence.py"
    cp ${../../attacks/networks.py} "$out/networks.py"
    cp ${../../attacks/events.py} "$out/events.py"
  '';
  intelligencePython = pkgs.python3.withPackages (ps: [ ps.maxminddb ]);
in
{
  environment.etc."attacks/ssh-keys.json" = {
    mode = "0444";
    text = builtins.toJSON (
      (lib.mapAttrs (_: user: user.openssh.authorizedKeys.keys)
        (lib.filterAttrs (_: user: user.openssh.authorizedKeys.keys != [ ]) config.users.users))
      // {
        studio-tunnel = lib.filter (line: line != "")
          (lib.splitString "\n" config.environment.etc."ssh/studio-transfer-keys".text);
      }
    );
  };

  systemd.services.attacks-intelligence = {
    description = "Refresh offline location, ASN, cloud and relay datasets";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    onFailure = [ "ntfy-failure@%n.service" ];
    environment.SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${intelligencePython}/bin/python3 ${intelligence}/update_intelligence.py /var/lib/attacks-intelligence";
      DynamicUser = true;
      StateDirectory = "attacks-intelligence";
      StateDirectoryMode = "0755";
      UMask = "0022";
      NoNewPrivileges = true;
      CapabilityBoundingSet = "";
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      PrivateDevices = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectControlGroups = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
      LockPersonality = true;
      MemoryMax = "768M";
      TasksMax = 16;
      TimeoutStartSec = "10min";
    };
  };
  systemd.timers.attacks-intelligence = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2min";
      OnCalendar = "*-*-* 02:45:00";
      RandomizedDelaySec = "15min";
      Persistent = true;
    };
  };

  systemd.services.attacks-connections = {
    description = "Passive public service connection metadata for attacks.danteb.com";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = [ pkgs.tcpdump ];
    environment.ATTACKS_INTERFACE = "bond0";
    serviceConfig = {
      ExecStart = "${pkgs.python3}/bin/python3 -u ${capture}/capture.py";
      Restart = "on-failure";
      RestartSec = 10;
      DynamicUser = true;
      AmbientCapabilities = [ "CAP_NET_RAW" ];
      CapabilityBoundingSet = [ "CAP_NET_RAW" ];
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      PrivateDevices = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectControlGroups = true;
      RestrictAddressFamilies = [ "AF_PACKET" "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      LockPersonality = true;
      MemoryMax = "128M";
      TasksMax = 16;
      UMask = "0077";
      TimeoutStopSec = 10;
    };
  };
}
