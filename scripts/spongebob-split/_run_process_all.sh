#!/usr/bin/env bash
set -e
export HOME=/home/danteb
export PATH=/run/current-system/sw/bin:/usr/bin:/bin:$PATH
export USER=danteb
cd ~/spongebob-split
for s in 2 3 4 5; do
  echo "=== Season $s ===" | tee -a /tmp/process_all.log
  nix shell nixpkgs#ffmpeg nixpkgs#python3 -c bash -lc "python3 06_process_season.py $s --force" >> /tmp/process_s$s.log 2>&1
  echo "=== Season $s done ===" | tee -a /tmp/process_all.log
done
touch /tmp/process_all_done.flag
