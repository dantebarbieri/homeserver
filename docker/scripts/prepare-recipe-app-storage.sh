#!/bin/sh

set -eu

DATA_ROOT="${DATA_ROOT:-/srv/docker/data}"

case "$DATA_ROOT" in
  /*) ;;
  *)
    echo "DATA_ROOT must be an absolute path." >&2
    exit 1
    ;;
esac

if [ ! -d "$DATA_ROOT" ]; then
    echo "DATA_ROOT does not exist: $DATA_ROOT" >&2
    exit 1
fi

# Docker users can apply the numeric ownership without an interactive sudo
# prompt. Re-execute this same script as root in a minimal helper container.
if [ "$(id -u)" -ne 0 ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "Run as root or install Docker." >&2
        exit 1
    fi

    exec docker run --rm -i \
        -e DATA_ROOT="$DATA_ROOT" \
        -v "$DATA_ROOT:$DATA_ROOT" \
        alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce \
        sh -s < "$0"
fi

prepare_dir() {
    path="$1"
    uid="$2"
    gid="$3"

    if [ -L "$path" ]; then
        echo "Refusing to replace symlink: $path" >&2
        exit 1
    fi

    mkdir -p "$path"
    chown "$uid:$gid" "$path"
    chmod 0750 "$path"
    printf '%s (uid=%s gid=%s)\n' "$path" "$uid" "$gid"
}

# Runtime IDs come from the exact images pinned in compose.recipe-apps.yml.
prepare_dir "$DATA_ROOT/recipe-gpt-sol" 1000 1000
prepare_dir "$DATA_ROOT/recipe-gemini/recipes" 1001 65533
prepare_dir "$DATA_ROOT/recipe-claude" 1000 1000
prepare_dir "$DATA_ROOT/recipe-claude/recipes" 1000 1000
prepare_dir "$DATA_ROOT/recipe-grok/recipes" 100 101
