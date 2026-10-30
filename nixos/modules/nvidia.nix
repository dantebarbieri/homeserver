# NVIDIA GPU driver, container toolkit and Plex hardware-transcoding check.
{ config, pkgs, ... }:

{
  # NVIDIA (RTX 2070 SUPER — production driver, headless with persistenced)
  services.xserver.videoDrivers = [ "nvidia" ];  # driver registration only, does not enable X11
  hardware = {
    graphics.enable = true;
    nvidia = {
      modesetting.enable = true;
      open = true;
      nvidiaPersistenced = true;  # keeps GPU initialized without X/Wayland (headless)
      nvidiaSettings = false;
      package = config.boot.kernelPackages.nvidiaPackages.production;
    };
    nvidia-container-toolkit.enable = true;
  };

  # Prevent nixos-rebuild switch from failing due to in-use NVIDIA modules.
  # During --upgrade the new driver is on disk but old modules are in memory;
  # restarting these services before a reboot causes version-mismatch failures.
  systemd.services.nvidia-persistenced.restartIfChanged = false;
  systemd.services.nvidia-container-toolkit-cdi-generator.restartIfChanged = false;

  # Plex can remain healthy while silently falling back to CPU transcoding.
  # Exercise its actual CUDA/NVENC path and alert if a driver/image update
  # breaks hardware acceleration.
  systemd.services.plex-hwaccel-check = {
    description = "Verify Plex hardware transcoding";
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker coreutils ];
    serviceConfig.Type = "oneshot";
    script = ''
      ${pkgs.bash}/bin/bash /srv/homeserver/docker/scripts/check-plex-hwaccel.sh
    '';
  };

  systemd.timers.plex-hwaccel-check = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "15m";
      OnUnitActiveSec = "6h";
      RandomizedDelaySec = "10m";
    };
  };
}
