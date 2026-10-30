# Home Manager configuration for danteb: zsh (with Zim) and git identity.
#
# Everything here is copied into the world-readable Nix store, so never put
# secrets in this file. Keep them in ~/.zprofile.local (login shells) or
# ~/.zshrc.local (interactive shells); both are sourced when present and are
# not managed by Home Manager.
{ config, pkgs, ... }:

{
  home.stateVersion = "26.11";

  programs.git = {
    enable = true;
    settings = {
      user = {
        name = "dantebarbieri";
        email = "dantevbarbieri@gmail.com";
      };
      commit.gpgSign = true;
    };
    signing = {
      key = "~/.ssh/id_ed25519.pub";
      format = "ssh";
    };
  };

  programs.zsh = {
    enable = true;
    dotDir = config.home.homeDirectory;
    # Zim's completion module runs compinit; a second run only slows startup.
    enableCompletion = false;
    defaultKeymap = "emacs";
    autocd = true;
    # Matches what Zim's environment module set on top of the old ~/.zshrc.
    history = {
      path = "${config.home.homeDirectory}/.histfile";
      size = 20000;
      save = 10000;
      append = true;
      ignoreDups = true;
      ignoreAllDups = true;
      findNoDups = true;
      ignoreSpace = true;
      share = true;
    };
    profileExtra = ''
      if [[ -r ~/.zprofile.local ]]; then
        source ~/.zprofile.local
      fi
    '';
    initContent = ''
      # Remove path separator from WORDCHARS.
      WORDCHARS=''${WORDCHARS//[\/]}
      # zsh-autosuggestions is the last Zim module, so skip per-prompt rebinding.
      ZSH_AUTOSUGGEST_MANUAL_REBIND=1
      ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets)

      # Zim: zimfw comes from Nix; modules are fetched into ~/.zim on first use
      # and init.zsh is rebuilt whenever ~/.zimrc changes (see home.file below).
      ZIM_HOME=''${HOME}/.zim
      if [[ ! ''${ZIM_HOME}/init.zsh -nt ''${HOME}/.zimrc ]]; then
        source ${pkgs.zimfw}/zimfw.zsh init
      fi
      source ''${ZIM_HOME}/init.zsh

      # zsh-history-substring-search: bind keys after Zim so up/down work both
      # before and after zle-line-init.
      zmodload -F zsh/terminfo +p:terminfo
      for key ('^[[A' '^P' ''${terminfo[kcuu1]}) bindkey ''${key} history-substring-search-up
      for key ('^[[B' '^N' ''${terminfo[kcud1]}) bindkey ''${key} history-substring-search-down
      for key ('k') bindkey -M vicmd ''${key} history-substring-search-up
      for key ('j') bindkey -M vicmd ''${key} history-substring-search-down
      unset key

      # After Zim's compinit so `z` gets completions.
      eval "$(zoxide init zsh)"

      if [[ -e ~/.iterm2_shell_integration.zsh ]]; then
        source ~/.iterm2_shell_integration.zsh
      fi
      if [[ -r ~/.zshrc.local ]]; then
        source ~/.zshrc.local
      fi
    '';
  };

  home.file.".zimrc" = {
    # Rebuild ~/.zim/init.zsh on the next shell. The symlinked ~/.zimrc has a
    # store mtime, so zimfw's own freshness check never fires.
    onChange = ''run rm -f "$HOME/.zim/init.zsh"'';
    text = ''
      # Managed by Home Manager (nixos/home/danteb.nix).
      # zimfw: ${pkgs.zimfw}

      zmodule environment
      zmodule git
      zmodule input
      zmodule termtitle
      zmodule utility

      # Prompt
      zmodule duration-info
      zmodule git-info
      zmodule asciiship

      # Completion: completion must come after modules that add definitions.
      zmodule zsh-users/zsh-completions --fpath src
      zmodule completion

      # Must be initialized last, in this order.
      zmodule zsh-users/zsh-syntax-highlighting
      zmodule zsh-users/zsh-history-substring-search
      zmodule zsh-users/zsh-autosuggestions
    '';
  };
}
