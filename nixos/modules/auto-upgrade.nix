# Unattended NixOS upgrades.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    mirklurkDeploymentCondition;
in
{
  # NixOS auto-upgrade (daily at 04:30, after Docker update at 04:00)
  # Stage the next boot without switching NVIDIA userspace under loaded modules.
  # Activation (including OS security updates) requires a planned reboot.
  system.autoUpgrade = {
    enable = true;
    dates = "04:30";
    operation = "boot";
    allowReboot = false;
  };
  systemd.services.nixos-upgrade.unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
  systemd.timers.nixos-upgrade.unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
}
