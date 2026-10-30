#!/bin/bash
# PostToolUse hook: remind Claude to verify NixOS options after editing NixOS modules
# Receives JSON on stdin with tool_input.file_path

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only trigger for Nix files under nixos/ (configuration, modules, home, flake)
if [[ ! "$FILE_PATH" =~ nixos/.*\.nix$ ]]; then
  exit 0
fi

cat <<'EOF'
IMPORTANT: You just edited a NixOS/Home Manager Nix file. Before proceeding, verify any NEW or CHANGED options:

1. Use /nixos-option <option.path> to look up each new option (Home Manager options live under nixos/home/; check https://home-manager-options.extranix.com or the home-manager source)
2. Confirm the option exists and the value type is correct
3. Check for deprecation warnings or renamed options (e.g. extraConfig → settings)
4. Common pitfalls: wrong nesting depth, string vs boolean, removed options in newer NixOS
5. Never put secrets in Nix files: they are public in this repo and world-readable in /nix/store
6. `git add` new files — the flake only sees tracked files

Do NOT assume an option path is correct from memory — always verify.
EOF

exit 0
