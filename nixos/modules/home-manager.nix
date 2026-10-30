# Home Manager, integrated into NixOS: user dotfiles are built with the system
# and applied on activation. Per-user configs live in ../home.
{ inputs, ... }:

{
  imports = [ inputs.home-manager.nixosModules.home-manager ];

  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    # Move pre-existing unmanaged files aside (~/.zshrc -> ~/.zshrc.hm-backup)
    # instead of failing activation.
    backupFileExtension = "hm-backup";
    users.danteb = import ../home/danteb.nix;
  };
}
