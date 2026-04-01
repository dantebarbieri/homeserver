# Nix convenience functions
# Sourced by NixOS interactiveShellInit (programs.zsh) — see configuration.nix

# Try packages without installing
# Usage: nsp hello cowsay        →   nix shell nixpkgs#hello nixpkgs#cowsay
# Chain: nsp $(nwp dig bc)       →   nix shell nixpkgs#dnsutils nixpkgs#bc
nsp() {
  local args=()
  local line
  # Split each argument on newlines so $(nwp dig bc) works seamlessly in ZSH
  # (ZSH doesn't word-split command substitution by default)
  for arg in "$@"; do
    while IFS= read -r line; do
      [[ -n "$line" ]] && args+=("nixpkgs#$line")
    done <<< "$arg"
  done
  nix shell "${args[@]}"
}

# Search nixpkgs by name or description
# Usage: nss neovim   →   nix search nixpkgs neovim
nss() { nix search nixpkgs "$@" 2>/dev/null; }

# Find which package provides a binary (requires nix-index database)
# Usage: nwp dig             →   dnsutils  (169K)
# Chain: nsp $(nwp dig)      →   nix shell nixpkgs#dnsutils
# Chain: nsp $(nwp dig bc)   →   nix shell nixpkgs#dnsutils nixpkgs#bc
nwp() {
  local db="$HOME/.cache/nix-index/files"
  if [[ ! -f "$db" ]]; then
    echo "nix-index database not found, building (this takes ~10 min)..." >&2
    nix-index
  fi

  # Support multiple binaries: nwp dig bc curl → one package per binary
  local all_results=()
  for bin in "$@"; do
    # nix-locate output: "package.output  SIZE TYPE PATH"
    # Strip the last .component (output name) to recover the package name.
    local results
    results=$(nix-locate -w "/bin/$bin" | awk '{
      pkg = $1; sub(/\.[^.]+$/, "", pkg)
      gsub(/,/, "", $2)
      if (!seen[pkg]++) print pkg, $2
    }')
    if [[ -z "$results" ]]; then
      echo "no package found providing /bin/$bin" >&2
      continue
    fi
    if [[ -t 1 ]]; then
      echo "$results" | while read -r pkg bytes; do
        if [[ -n "$bytes" && "$bytes" -gt 0 ]] 2>/dev/null; then
          printf "%s  (%s)\n" "$pkg" "$(numfmt --to=iec "$bytes")"
        else
          printf "%s\n" "$pkg"
        fi
      done
    else
      all_results+=("$(echo "$results" | head -1 | awk '{print $1}')")
    fi
  done

  # In pipe mode, output all resolved packages (one per line for single,
  # space-separated for nsp compatibility)
  if [[ ! -t 1 && ${#all_results[@]} -gt 0 ]]; then
    printf "%s\n" "${all_results[@]}"
  elif [[ ! -t 1 ]]; then
    return 1
  fi
}
