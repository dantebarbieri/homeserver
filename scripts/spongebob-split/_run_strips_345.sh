#!/usr/bin/env bash
set -e
PATH=/run/current-system/sw/bin:/usr/bin:/bin:$PATH
cd ~/spongebob-split
for s in 3 4 5; do
  nix shell nixpkgs#ffmpeg nixpkgs#python3 -c bash -lc "python3 02_make_titlecard_strips.py $s" > /tmp/strips_s$s.log 2>&1
done
touch /tmp/strips_all_done.flag
