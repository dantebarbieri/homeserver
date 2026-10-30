# Compatibility shims for prebuilt (non-Nix) binaries.
{ pkgs, ... }:

{
  # nix-ld: provide a real /lib64/ld-linux-x86-64.so.2 so manylinux Python
  # wheels (pygplates, landlab, pyfastnoiselite, …) can dlopen on NixOS.
  # Without this, /lib64/ld-linux-x86-64.so.2 is the NixOS stub-ld and any
  # mmap of a manylinux .so segment fails with "failed to map segment from
  # shared object". Required by the WorldForge Forgejo Actions runner.
  programs.nix-ld.enable = true;
  programs.nix-ld.libraries = with pkgs; [
    stdenv.cc.cc.lib  # libstdc++, libgcc_s
    zlib
    glib
    libGL
    libGLU
    glew
    freetype
    fontconfig
    expat
    openssl
    libxml2
    sqlite
    libx11
    libxext
    libsm
    libice
    libxrender
    libxcb
    libxi
    libxrandr
    libxcursor
    libxfixes
    libxdamage
    libxcomposite
    libxtst
    qt5.qtbase
    boost
    gdal
    proj
    geos
    libtiff
    libjpeg
    libpng
  ];

  # envfs: FUSE-backed /bin and /usr/bin that dynamically resolve to the
  # current system profile. NixOS normally ships only /bin/sh and
  # /usr/bin/env; third-party software (e.g. ExoPlaSim's compile.sh with
  # `#!/bin/bash`, conda hooks, manylinux helpers) routinely assumes a
  # full FHS layout and fails with "bad interpreter" otherwise. envfs
  # patches over the entire class of issue without per-package symlinks.
  # See: https://github.com/Mic92/envfs
  services.envfs.enable = true;
}
