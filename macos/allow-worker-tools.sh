#!/bin/bash
set -euo pipefail

[[ "$(uname -s)" == Darwin && "$(id -u)" == 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]] || {
    echo "Run with sudo from the Homebrew owner's account." >&2
    exit 1
}
id _studio >/dev/null
brew=/opt/homebrew/bin/brew
packages="$(
    for package in ffmpeg uv ollama; do
        printf '%s\n' "$package"
        sudo -u "$SUDO_USER" "$brew" deps --installed --formula "$package"
    done | sort -u
)"

# Keep package writes administrator-only; grant this account runtime access.
grant_search() {
    if ! ls -lde "$1" | grep -q 'user:_studio allow .*search'; then
        chmod +a '_studio allow search' "$1"
    fi
}
for directory in bin opt Cellar lib share etc; do
    grant_search "/opt/homebrew/$directory"
done
while IFS= read -r package; do
    prefix="$(sudo -u "$SUDO_USER" "$brew" --prefix "$package")"
    actual="$(cd "$prefix" && pwd -P)"
    [[ "$actual" == /opt/homebrew/Cellar/*/* ]] || {
        echo "Refusing a non-Cellar package path: $actual" >&2
        exit 1
    }
    grant_search "$(dirname "$actual")"
    if ! ls -lde "$actual" | grep -q 'user:_studio allow list,search,readattr,readextattr'; then
        chmod -R -P +a '_studio allow read,execute,readattr,readextattr' "$actual"
    fi
    printf 'Granted worker runtime access: %s\n' "$package"
done <<<"$packages"

sudo -u _studio /opt/homebrew/bin/uv --version
sudo -u _studio /opt/homebrew/bin/ffmpeg -version
