# Suggested Home Directory Changes

Your NixOS `configuration.nix` now manages several things that previously
lived only in your dotfiles. The changes below remove duplication and let
the system config be the single source of truth.

> **These files are in your home directory and are not version-controlled.**
> Make these changes manually on the server.

---

## 1. Remove `setopt no_global_rcs` from `~/.zshenv`

**Why:** This option tells ZSH to skip `/etc/zshrc`, which is where NixOS
puts the `interactiveShellInit` content (zimfw auto-download,
`any-nix-shell`, `fastfetch`, shell aliases). With `no_global_rcs` set,
none of that runs for your user.

**Action:** Delete or comment out the line:

```bash
# ~/.zshenv — remove this line:
setopt no_global_rcs
```

If the file is now empty, you can delete it entirely:

```bash
rm ~/.zshenv
```

> **If you prefer to keep `no_global_rcs`**, the system-level
> `interactiveShellInit` will be ignored and you must keep the equivalent
> setup in your `~/.zshrc` (zimfw download, fastfetch, etc.). Everything
> still works — you just manage it yourself.

---

## 2. Remove duplicate zimfw download from `~/.zshrc`

**Why:** The NixOS config now auto-downloads zimfw in the system-wide
`interactiveShellInit`. Keeping both is harmless (the check is
idempotent) but redundant.

**Action:** Remove these lines from `~/.zshrc`:

```zsh
# REMOVE — now handled by NixOS interactiveShellInit:
# Download zimfw plugin manager if missing.
if [[ ! -e ${ZIM_HOME}/zimfw.zsh ]]; then
  if (( ${+commands[curl]} )); then
    curl -fsSL --create-dirs -o ${ZIM_HOME}/zimfw.zsh \
        https://github.com/zimfw/zimfw/releases/latest/download/zimfw.zsh
  else
    mkdir -p ${ZIM_HOME} && wget -nv -O ${ZIM_HOME}/zimfw.zsh \
        https://github.com/zimfw/zimfw/releases/latest/download/zimfw.zsh
  fi
fi
```

**Keep** the module install and init lines that follow:

```zsh
# KEEP — these must run AFTER your module config (ZSH_AUTOSUGGEST_*, etc.)
if [[ ! ${ZIM_HOME}/init.zsh -nt ${ZIM_CONFIG_FILE:-${ZDOTDIR:-${HOME}}/.zimrc} ]]; then
  source ${ZIM_HOME}/zimfw.zsh init
fi
source ${ZIM_HOME}/init.zsh
```

---

## 3. Remove `fastfetch` call from `~/.zshrc`

**Why:** `fastfetch` is now called in the system-wide `interactiveShellInit`.
Having it in both places means it runs twice per shell.

**Action:** Remove the last line of `~/.zshrc`:

```zsh
# REMOVE — now system-wide:
fastfetch
```

---

## 4. Remove SSH agent setup from `~/.zshrc`

**Why:** NixOS already manages the SSH agent via `programs.ssh.startAgent = true`.
Your manual agent setup (lines 140–150 of `.zshrc`) can conflict with the
system-managed agent.

**Action:** Remove the **custom socket setup** but **keep the key-loading line**.

NixOS already starts the agent and provides `$SSH_AUTH_SOCK`. Running a
second agent creates two competing sockets — keys added to one aren't
visible in the other. However, the NixOS agent does **not** auto-load
keys, so the `ssh-add` line is still useful (it loads your default key
on first login so git signing works without repeated passphrase prompts).

```zsh
# REMOVE — NixOS already provides the agent socket:
SSH_AGENT_SOCK="${XDG_RUNTIME_DIR:-/tmp}/ssh-agent-${USER}.sock"

if [[ ! -S "$SSH_AGENT_SOCK" ]]; then
  eval "$(ssh-agent -a "$SSH_AGENT_SOCK" 2>/dev/null)"
fi
export SSH_AUTH_SOCK="$SSH_AGENT_SOCK"

# KEEP — loads your default key into the NixOS-managed agent on first login:
ssh-add -l &>/dev/null || ssh-add 2>/dev/null
```

---

## 5. Use `nix shell` instead of `nix-shell -p`

**Why:** You already have flakes enabled. The modern `nix shell` command
stays in your current shell (ZSH) and doesn't drop you into bash.

**Before (drops into bash):**
```bash
nix-shell -p hello
```

**After (stays in ZSH):**
```bash
nix shell nixpkgs#hello
```

**Convenience shortcuts** (defined in your NixOS config):

| Alias / Function | Expands to |
|---|---|
| `ns` | `nix shell` |
| `nr` | `nix run` |
| `nsp hello cowsay` | `nix shell nixpkgs#hello nixpkgs#cowsay` |

> **Fallback:** Even if you use the old `nix-shell -p`, the `any-nix-shell`
> integration will keep you in ZSH instead of dropping to bash.

---

## Summary of `~/.zshrc` After Cleanup

After applying changes 2–4, your `~/.zshrc` should look approximately like:

```zsh
# Zsh configuration (history, input, etc.)
HISTFILE=~/.histfile
HISTSIZE=1000
SAVEHIST=1000
setopt HIST_IGNORE_ALL_DUPS
bindkey -e
WORDCHARS=${WORDCHARS//[\/]}
setopt autocd nomatch

# Zim module configuration
ZSH_AUTOSUGGEST_MANUAL_REBIND=1
ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets)

# Initialize modules
ZIM_HOME=${ZDOTDIR:-${HOME}}/.zim
if [[ ! ${ZIM_HOME}/init.zsh -nt ${ZIM_CONFIG_FILE:-${ZDOTDIR:-${HOME}}/.zimrc} ]]; then
  source ${ZIM_HOME}/zimfw.zsh init
fi
source ${ZIM_HOME}/init.zsh

# Post-init: history substring search keybindings
zmodload -F zsh/terminfo +p:terminfo
for key ('^[[A' '^P' ${terminfo[kcuu1]}) bindkey ${key} history-substring-search-up
for key ('^[[B' '^N' ${terminfo[kcud1]}) bindkey ${key} history-substring-search-down
for key ('k') bindkey -M vicmd ${key} history-substring-search-up
for key ('j') bindkey -M vicmd ${key} history-substring-search-down
unset key

# Functions & Aliases
dcu() ( ... )
dcupdate() ( ... )

# Tools
eval "$(zoxide init zsh)"
```
