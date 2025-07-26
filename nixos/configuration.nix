# Edit this configuration file to define what should be installed on
# your system. Help is available in the configuration.nix(5) man page, on
# https://search.nixos.org/options and in the NixOS manual (`nixos-help`).

{ config, lib, pkgs, ... }:

{
  imports =
    [ # Include the results of the hardware scan.
      ./hardware-configuration.nix
    ];

  # Use the systemd-boot EFI boot loader.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # Allow Proprietary
  nixpkgs.config.allowUnfree = true;

  networking.hostName = "homeserver"; # Define your hostname.

  # Configure network connections interactively with nmcli or nmtui.
  networking.networkmanager.enable = false;
  networking.wireless.enable = true;
  systemd.network.enable = true;

  networking.wireless.secretsFile = "/run/secrets/wireless.conf";
  networking.wireless.networks."Aggies R Us".psk = "ext:password";

  systemd.network.networks = {
    # Wi‑Fi primary (metric 100)
    "10-wifi" = {
      matchConfig.Name = "wlp193s0";
      networkConfig = {
        # static addresses (primary + floating .100)
        Address    = [ "192.168.1.26/24" "192.168.1.100/24" ];
        Gateway    = "192.168.1.1";
        DNS        = [ "192.168.1.1" "1.1.1.1" ];
        RouteMetric = 100;
      };
    };

    # PowerLine backup 0 (metric 200)
    "20-pl0" = {
      matchConfig.Name = "enp66s0f0";
      networkConfig = {
        Address     = [ "192.168.1.24/24" ];
        Gateway     = "192.168.1.1";
        RouteMetric = 200;
      };
      linkConfig = {
        RequiredForOnline = "no";
      };
    };

    # PowerLine backup 1 (metric 300)
    "30-pl1" = {
      matchConfig.Name = "enp66s0f1";
      networkConfig = {
        Address     = [ "192.168.1.25/24" ];
        Gateway     = "192.168.1.1";
        RouteMetric = 300;
      };
      linkConfig = {
        RequiredForOnline = "no";
      };
    };
  };

  # Set your time zone.
  time.timeZone = "America/Chicago";

  # Configure network proxy if necessary
  # networking.proxy.default = "http://user:password@proxy:port/";
  # networking.proxy.noProxy = "127.0.0.1,localhost,internal.domain";

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";
  console = {
    font = "Lat2-Terminus16";
    keyMap = "us";
  #   useXkbConfig = true; # use xkb.options in tty.
  };

  # Enable the X11 windowing system.
  # services.xserver.enable = true;

  # Enable Flakes (Experimental)
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Configure keymap in X11
  # services.xserver.xkb.layout = "us";
  # services.xserver.xkb.options = "eurosign:e,caps:escape";

  # Enable CUPS to print documents.
  # services.printing.enable = true;

  # Enable sound.
  # services.pulseaudio.enable = true;
  # OR
  # services.pipewire = {
  #   enable = true;
  #   pulse.enable = true;
  # };

  # Enable touchpad support (enabled default in most desktopManager).
  # services.libinput.enable = true;

  # Define a user account. Don't forget to set a password with ‘passwd’.
  users = {
    defaultUserShell = pkgs.zsh;
    users.danteb = {
      initialPassword = "changeme123!";
      isNormalUser = true;
      extraGroups = [ "docker" "wheel" ]; # Enable ‘sudo’ for the user.
      openssh.authorizedKeys = [
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBH5PB799wDZ5lqHUn0HDnEudAaUk9ihMYk2/vE7O8ZZ+ykEEycFa1BFxVP4EnIe9J9jyD9GVYs2vgngMNFEmeAE=" # Dante's iPhone (Termius)
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGSElIxTg8VbjbB3O2WVMvZJYfP4GBzg5uzJSaKKu12f dantevbarbieri@gmail.com" # Dante's MacBook Pro
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPdijU1XLbXrh1yMq7RtrLrIaTtWibnMAFcxTfFm1Y+g dantevbarbieri@gmail.com"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHGJVxpke1XAdXybnz5HUkZBx9sDLqaJSsghrItLoDRj redmond\dbarbieri@DESKTOP-JG75H93" # Dante Work PC
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFYsa3JuUbgxuC6O+rfxSIC4scGcxhlgig+wXVoEMaCe dantevbarbieri@gmail.com" # Dell Latitude E5550
      ];
      packages = with pkgs; [
        tree
      ];
    };
  };

  # programs.firefox.enable = true;
  programs.git = {
    enable = true;
    extraConfig = {
      push = { autoSetupRemote = true; };
    };
    userName  = "dantebarbieri";
    userEmail = "dantevbarbieri@gmail.com";
  };
  programs.neovim = {
    enable = true;
    defaultEditor = true;
    vimAlias = true;
    viAlias = true;
  };
  programs.zsh.enable = true;

  # List packages installed in system profile.
  # You can use https://search.nixos.org/ to find more packages (and options).
  environment.systemPackages = with pkgs; [
    neovim # Do not forget to add an editor to edit configuration.nix! The Nano editor is also installed by default.
    wget

    # Storage tooling
    mdadm
    lvm2
    dosfstools    # FAT/VFAT helpers
    xfsprogs      # XFS helpers
    parted        # Partitioning

    # Docker
    docker-compose
  ];

  # Some programs need SUID wrappers, can be configured further or are
  # started in user sessions.
  # programs.mtr.enable = true;
  programs.gnupg.agent = {
    enable = true;
    enableSSHSupport = true;
  };

  # List services that you want to enable:

  # Enable the OpenSSH daemon.
  services.openssh = {
    enable = true;
    ports = [ 28 ];
    settings = {
      PermitRootLogin = "no";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    };
  };

  # Open ports in the firewall.
  # networking.firewall.allowedTCPPorts = [ ... ];
  # networking.firewall.allowedUDPPorts = [ ... ];
  # Or disable the firewall altogether.
  # networking.firewall.enable = false;

  # Copy the NixOS configuration file and link it from the resulting system
  # (/run/current-system/configuration.nix). This is useful in case you
  # accidentally delete configuration.nix.
  # system.copySystemConfiguration = true;

  # Enable Docker.
  virtualisation.docker.enable = true;

  # NVIDIA
  hardware = {
    graphics.enable = true;

    nvidia = {
      # Enable kernel modesetting for tear-free output
      modesetting.enable = true;

      # Choose the open-source kernel module (Turing+ only)
      open = true;

      # Whether to install the `nvidia-settings` GUI tool
      nvidiaSettings.enable = false;

      # Pin a driver version if desired (stable, beta, production, or legacy)
      # package = config.boot.kernelPackages.nvidiaPackages.stable;
    };

    nvidia-container-toolkit.enable = true;
  };

  # Use DoAs instead of SUDo
  security = {
    doas = {
      enable = true;
      extraRules = [ { groups = [ "wheel" ]; keepEnv = true; }]
    };
    sudo.enable = false;
  };

  # This option defines the first version of NixOS you have installed on this particular machine,
  # and is used to maintain compatibility with application data (e.g. databases) created on older NixOS versions.
  #
  # Most users should NEVER change this value after the initial install, for any reason,
  # even if you've upgraded your system to a new NixOS release.
  #
  # This value does NOT affect the Nixpkgs version your packages and OS are pulled from,
  # so changing it will NOT upgrade your system - see https://nixos.org/manual/nixos/stable/#sec-upgrading for how
  # to actually do that.
  #
  # This value being lower than the current NixOS release does NOT mean your system is
  # out of date, out of support, or vulnerable.
  #
  # Do NOT change this value unless you have manually inspected all the changes it would make to your configuration,
  # and migrated your data accordingly.
  #
  # For more information, see `man configuration.nix` or https://nixos.org/manual/nixos/stable/options#opt-system.stateVersion .
  system.stateVersion = "25.11"; # Did you read the comment?

}

