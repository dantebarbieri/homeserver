# Unattended NixOS upgrades.
{ config, lib, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    mirklurkDeploymentCondition;
in
{
  # NixOS auto-upgrade (daily at 04:30, after Docker update at 04:00)
  # Builds the flake exactly as locked on the main branch docker-compose-update
  # just pulled; CI keeps flake.lock fresh. git+file copies only tracked files
  # into the store, so the untracked docker/.env never reaches it, and ref=main
  # takes committed content only, so uncommitted edits (or a secret pasted into
  # a tracked file) are neither built nor copied into the world-readable store.
  # Stage the next boot without switching NVIDIA userspace under loaded modules.
  # Activation (including OS security updates) requires a planned reboot.
  system.autoUpgrade = {
    enable = true;
    # The module splices this into the upgrade script unquoted; without the
    # quoting, `&` would background nixos-rebuild and skip the upgrade.
    flake = lib.escapeShellArg "git+file:///srv/homeserver?dir=nixos&ref=main#homeserver";
    upgrade = false;
    flags = [ "--no-update-lock-file" ];
    dates = "04:30";
    operation = "boot";
    allowReboot = false;
  };
  systemd.services.nixos-upgrade.unitConfig = {
    ConditionPathExists = mirklurkDeploymentCondition;
    # A failed build would otherwise silently stop the server taking updates.
    OnFailure = "ntfy-failure@%n.service";
  };
  systemd.timers.nixos-upgrade.unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
}
