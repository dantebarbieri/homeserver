{
  description = "NixOS configuration for the homeserver";

  # flake.lock pins these. CI (.github/workflows/nixos-flake-update.yml)
  # updates it daily after the new lock evaluates; the server applies it at
  # the 04:30 nixos-upgrade (modules/auto-upgrade.nix).
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Weekly prebuilt nix-locate database (modules/shell.nix), so the server
    # never has to index nixpkgs itself.
    nix-index-database = {
      url = "github:nix-community/nix-index-database";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, ... }@inputs:
    {
      nixosConfigurations.homeserver = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs; };
        modules = [ ./configuration.nix ];
      };
    };
}
