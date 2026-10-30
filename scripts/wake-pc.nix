{ pkgs ? import <nixpkgs> { } }:

pkgs.writeScriptBin "wake-pc" (
  "#!${pkgs.python3}/bin/python3\n" + builtins.readFile ./wake-pc.py
)
