#!/bin/sh
# Flatten the Copernicus DEM tilesets into a directory opentopodata can parse.
#
# Two problems with the raw Copernicus layout:
#   1. Each tile ships as a nested directory with AUXFILES/ INFO/ PREVIEW/
#      subdirs full of unrelated .tif/.pdf/.kml/.xml files. Opentopodata's
#      flat recursive glob treats every non-AUX file as a raster and errors
#      out on the first oddball.
#   2. Tile filenames look like `Copernicus_DSM_COG_10_S04_00_E120_00_DEM.tif`
#      where `_00_` is an arcminute separator. Opentopodata's tile-coord
#      regex `[NS]\d+_?[WE]\d+` only accepts a single optional underscore
#      between the N/S number and the W/E letter, so those names don't parse.
#
# Build a symlink farm of just the primary *_DEM.tif files, renaming each
# symlink to the minimal `N20W120.tif` form that opentopodata's parser is
# built for. The source mount stays read-only; only the derived farm lives
# in the container's writable layer.
set -eu

python3 - <<'PY'
import os, re, sys

PAIRS = [
    ("/app/data/copernicus-glo30", "/app/data-flat/cop30"),
    ("/app/data/srtm30m", "/app/data-flat/srtm30m"),
]
# Matches e.g. "…_S04_00_E120_00_DEM.tif" → groups ("S04", "E120").
DEM_RE = re.compile(r"_([NS]\d+)_\d+_([WE]\d+)_\d+_DEM\.tif$", re.IGNORECASE)

for src, dst in PAIRS:
    if not os.path.isdir(src):
        print(f"entrypoint: source '{src}' missing, skipping", file=sys.stderr)
        continue
    os.makedirs(dst, exist_ok=True)
    # Drop stale symlinks so a shrunken source doesn't leave dangling links.
    for name in os.listdir(dst):
        p = os.path.join(dst, name)
        if os.path.islink(p):
            os.unlink(p)
    linked = 0
    for tile_dir in os.scandir(src):
        if not tile_dir.is_dir():
            continue
        for entry in os.scandir(tile_dir.path):
            if not entry.is_file():
                continue
            m = DEM_RE.search(entry.name)
            if not m:
                continue
            link_name = f"{m.group(1)}{m.group(2)}.tif"
            link_path = os.path.join(dst, link_name)
            try:
                os.symlink(entry.path, link_path)
                linked += 1
            except FileExistsError:
                pass
    print(f"entrypoint: linked {linked} tiles into {dst}")
PY

exec "$@"
