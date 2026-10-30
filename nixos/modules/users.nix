# Login accounts.
{ pkgs, ... }:

{
  # User
  users = {
    defaultUserShell = pkgs.zsh;
    users.danteb = {
      initialPassword = "changeme123!";
      isNormalUser = true;
      extraGroups = [ "docker" "wheel" ];
      openssh.authorizedKeys.keys = [
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBH5PB799wDZ5lqHUn0HDnEudAaUk9ihMYk2/vE7O8ZZ+ykEEycFa1BFxVP4EnIe9J9jyD9GVYs2vgngMNFEmeAE=" # Dante's iPhone (Termius)
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGSElIxTg8VbjbB3O2WVMvZJYfP4GBzg5uzJSaKKu12f dantevbarbieri@gmail.com" # Dante's MacBook Pro
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPdijU1XLbXrh1yMq7RtrLrIaTtWibnMAFcxTfFm1Y+g dantevbarbieri@gmail.com"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEd1FMM7tj/1D8AIKc0ESGKLYx4Q6vEbDx8HxQAVD/IB REDMOND\dbarbieri@DESKTOP-PFQPS83" # Dante Work PC
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINH0/WsgjiI/Q3tlBsWudx9L3cApJOFxYl1lQP7Dd6/f Dante@DESKTOP-DD5K2PO" # Dante's Windows PC (DESKTOP-DD5K2PO)
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICj+eUZOCGI1eoaazJ7tXLFT9f8ElTlponq8NBBahl01 dante@DESKTOP-DD5K2PO-wsl" # Dante's WSL Ubuntu on DESKTOP-DD5K2PO
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC+RoHi5LOQGjERpsKhtgCkKzbm60ccYf1OzJKmin5B3 Dante@DESKTOP-13QOG4J homeserver 2026-07" # Dante's Windows PC (DESKTOP-13QOG4J)
      ];
      packages = with pkgs; [
        tree
        (import ../../scripts/wake-pc.nix { inherit pkgs; })
      ];
    };
  };
}
