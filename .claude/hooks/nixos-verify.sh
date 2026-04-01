#!/bin/bash
# PostToolUse hook: remind Claude to verify NixOS options after editing configuration.nix
# Receives JSON on stdin with tool_input.file_path

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only trigger for nixos/configuration.nix
if [[ ! "$FILE_PATH" =~ nixos/configuration\.nix$ ]]; then
  exit 0
fi

cat <<'EOF'
IMPORTANT: You just edited nixos/configuration.nix. Before proceeding, verify any NEW or CHANGED NixOS options:

1. Use /nixos-option <option.path> to look up each new option
2. Confirm the option exists and the value type is correct
3. Check for deprecation warnings or renamed options (e.g. extraConfig → settings)
4. Common pitfalls: wrong nesting depth, string vs boolean, removed options in newer NixOS

Do NOT assume an option path is correct from memory — always verify.
EOF

exit 0
