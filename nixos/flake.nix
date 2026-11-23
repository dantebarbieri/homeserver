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
    # `wake` CLI (modules/users.nix); the same tool installs itself on the
    # Mac Studio and Windows PC from the repo's releases.
    wake = {
      url = "github:dantebarbieri/wake";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, ... }@inputs:
    let
      system = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs; };
        modules = [ ./configuration.nix ];
      };
    in
    {
      # `homeserver` is the name scripts and CI use. Plain `nixos-rebuild`
      # picks the attribute matching the hostname, so also export `calcifer`.
      nixosConfigurations.homeserver = system;
      nixosConfigurations.calcifer = system;
    };
}
