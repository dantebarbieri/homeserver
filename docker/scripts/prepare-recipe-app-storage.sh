#!/usr/bin/env bash

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/srv/docker/data}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root so it can set the pinned images' runtime ownership." >&2
    exit 1
fi

prepare_dir() {
    local path="$1"
    local uid="$2"
    local gid="$3"

    if [[ -L "$path" ]]; then
        echo "Refusing to replace symlink: $path" >&2
        exit 1
    fi

    install -d -m 0750 -o "$uid" -g "$gid" "$path"
    printf '%s (uid=%s gid=%s)\n' "$path" "$uid" "$gid"
}

# Runtime IDs come from the exact images pinned in compose.recipe-apps.yml.
prepare_dir "$DATA_ROOT/recipe-gpt-sol" 1000 1000
prepare_dir "$DATA_ROOT/recipe-gemini/recipes" 1001 65533
prepare_dir "$DATA_ROOT/recipe-claude/recipes" 1000 1000
prepare_dir "$DATA_ROOT/recipe-grok/recipes" 100 101
