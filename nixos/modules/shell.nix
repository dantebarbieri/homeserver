# System-wide shell, editor and CLI tooling.
{ config, pkgs, inputs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; }) ntfyNotify;
in
{
  imports = [ inputs.nix-index-database.nixosModules.nix-index ];

  # Personal identity and commit signing live in Home Manager (../home).
  programs.git = {
    enable = true;
    config = {
      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      # The repo is owned by danteb, but root evaluates the flake in it
      # (nixos-upgrade) and pulls it (docker-compose-update).
      safe.directory = "/srv/homeserver";
    };
  };

  programs.neovim = {
    enable = true;
    defaultEditor = true;
    vimAlias = true;
    viAlias = true;
  };
  programs.zsh = {
    enable = true;
    enableCompletion = false;  # zimfw handles completion via its own module
    interactiveShellInit = ''
      # ── zimfw: auto-download plugin manager if missing ──
      ZIM_HOME="$HOME/.zim"
      if [[ ! -e "$ZIM_HOME/zimfw.zsh" ]]; then
        ${pkgs.curl}/bin/curl -fsSL --create-dirs -o "$ZIM_HOME/zimfw.zsh" \
          https://github.com/zimfw/zimfw/releases/latest/download/zimfw.zsh
      fi

      # ── any-nix-shell: stay in ZSH inside nix-shell / nix develop ──
      ${pkgs.any-nix-shell}/bin/any-nix-shell zsh --info-right | source /dev/stdin

      # ── Nix convenience functions (nsp, nss, nwp) ──
      source ${../nix-functions.zsh}

      # ── Docker Compose convenience functions ──
      source ${../docker-functions.zsh}

      # ── fastfetch: system info on initial shell only (not nix shell subshells) ──
      [[ $SHLVL -eq 1 ]] && fastfetch

    '';
    shellAliases = {
      ns = "nix shell";
      nr = "nix run";
    };
  };

  # List packages installed in system profile.
  # You can use https://search.nixos.org/ to find more packages (and options).
  environment = {
    systemPackages = with pkgs; [
      # NOTE: neovim is NOT listed here — programs.neovim.enable adds the wrapped
      # package (finalPackage) automatically. Listing pkgs.neovim again would
      # install the *unwrapped* copy alongside it.
      # Ref: https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/programs/neovim.nix

      # Kickstart.nvim external dependencies
      # Ref: https://github.com/nvim-lua/kickstart.nvim#install-external-dependencies
      gnumake          # provides `make`
      unzip
      gcc              # C compiler — needed to compile tree-sitter parsers
      ripgrep          # fast grep — used by Telescope live_grep
      fd               # fast find — used by Telescope find_files
      tree-sitter      # tree-sitter CLI — parser generator / grammar compiler
      # Clipboard: on a headless/SSH server, Neovim 0.10+ uses OSC 52 escape
      # sequences natively — no xclip/xsel/X11 needed on the server side.
      # Ref: https://neovim.io/doc/user/provider.html#clipboard-osc52
      # Nerd Font: install on your local (SSH client) machine, not here.
      # kickstart.nvim has vim.g.have_nerd_font = true in init.lua.

      bat
      curl
      wget
      zoxide
      fastfetch
      any-nix-shell
      # Storage tooling
      mdadm lvm2 dosfstools xfsprogs parted smartmontools
      # Docker
      docker-compose
      # Backup
      rclone
      pass             # general-purpose password store; preserve existing credentials
      # Typing practice
      gtypist toipe
      # General-purpose CLI helper: ntfy-notify "Title" "Message" [priority] [tags]
      ntfyNotify
    ];
    variables = {
      LESSOPEN = "| ${pkgs.bat}/bin/bat --color=always --style=plain --paging=never %s";
      LESS = "-R";
      MANROFFOPT = "-c";
      MANPAGER = "sh -c 'col -bx | bat -l man -p'";
    };
  };

  programs.gnupg.agent.enable = true;
  programs.ssh.startAgent = true;
  # nix-locate (and nwp) read the prebuilt database that nix-index-database
  # wraps into the package, pinned by flake.lock and refreshed by the nightly
  # lock update. The weekly local index this replaced peaked at ~14 GB of RAM
  # and had started failing.
  programs.nix-index.enable = true;
  programs.command-not-found.enable = false;  # mutually exclusive with nix-index shell integrations
}
