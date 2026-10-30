# ntfy failure handler shared by monitoring units. The ntfy-notify CLI is
# installed from modules/shell.nix.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic;
in
{
  # ── Generic ntfy failure handler ──────────────────────────────────────────
  # Wired via `unitConfig.OnFailure = "ntfy-failure@%n.service"` on units
  # whose normal failure path (an in-script curl) won't fire — e.g. when the
  # service is SIGTERM'd by TimeoutStartSec= or OOM-killed. Without this,
  # a timeout looks identical to a clean run from ntfy's perspective.
  systemd.services."ntfy-failure@" = {
    description = "ntfy alert for failed unit %i";
    scriptArgs = "%i";
    serviceConfig.Type = "oneshot";
    script = ''
      UNIT="$1"
      ${pkgs.curl}/bin/curl -s \
        -H "Title: $UNIT FAILED on ${config.networking.hostName}" \
        -H "Priority: high" \
        -H "Tags: warning,floppy_disk" \
        -d "systemd unit $UNIT exited abnormally (timeout, OOM, or non-zero exit). Inspect: journalctl -u $UNIT" \
        "${ntfyUrl}/${ntfyTopic}"
    '';
  };
}
