---
name: nixos-option
description: Look up NixOS options to verify they exist and are correctly used. Use when editing nixos/configuration.nix or when the PostToolUse hook reminds you to verify options.
allowed-tools: WebFetch, Bash, Grep, Read
---

Look up the NixOS option "$ARGUMENTS" to verify it exists and is correctly used.

## Steps

1. Fetch https://search.nixos.org/options?channel=unstable&query=$ARGUMENTS and extract:
   - Full option path
   - Type (bool, string, list, attrsOf, etc.)
   - Default value
   - Description
   - Example if available

2. If the page doesn't render (JS-only), fall back to searching the nixpkgs source:
   - Fetch `https://raw.githubusercontent.com/NixOS/nixpkgs/master/nixos/modules/` and find the relevant module file
   - Look for the mkOption definition matching the option name

3. Report the findings clearly so the user can verify their configuration.nix usage is correct.

4. If the option doesn't exist, suggest the closest valid alternatives.
