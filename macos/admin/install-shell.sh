#!/bin/sh
# Install the Studio's shell: dotfiles from admin/ plus the shared Ghibli
# prompt from ../shell. Run it as the admin user from a checkout; it is safe to
# run again.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
shared="$here/../../shell"

for f in zshenv zprofile zimrc zshrc; do
  install -m 0644 "$here/$f" "$HOME/.$f"
done

mkdir -p "$HOME/.config/ghibli"
install -m 0644 "$shared/prompt.zsh" "$HOME/.config/ghibli/prompt.zsh"

# Zim rebuilds its init script when .zimrc is newer, but drop it anyway so a
# changed module list is never missed.
rm -f "$HOME/.zim/init.zsh"
