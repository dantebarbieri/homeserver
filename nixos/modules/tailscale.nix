# Hosted mesh access; recovery routing belongs on No-Face, not this server.
{ ... }:

{
  services.tailscale = {
    enable = true;
    extraSetFlags = [
      "--accept-dns=false" # Keep AdGuard and systemd-resolved's existing DNS.
      "--accept-routes=false"
      "--ssh=false" # Retain OpenSSH's key authentication on port 28.
    ];
  };
}
