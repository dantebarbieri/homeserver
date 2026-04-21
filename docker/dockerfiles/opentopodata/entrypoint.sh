#!/bin/sh
# Flatten the Copernicus DEM tilesets into a directory opentopodata can parse.
#
# Each tile ships as a nested directory alongside AUXFILES/ INFO/ PREVIEW/
# subdirs full of unrelated .tif/.pdf/.kml/.xml files. opentopodata's flat
# recursive glob treats every non-AUX file as a raster and errors out on the
# first oddball. Symlink the primary *_DEM.tif for each tile into a flat dir
# and point the config at that instead, so opentopodata only ever sees files
# it was built to parse.
set -eu

for pair in "copernicus-glo30:cop30" "srtm30m:srtm30m"; do
    src="/app/data/${pair%:*}"
    dst="/app/data-flat/${pair#*:}"
    [ -d "$src" ] || { echo "entrypoint: source '$src' missing, skipping" >&2; continue; }
    mkdir -p "$dst"
    # Clear stale symlinks so a shrunken source doesn't leave dangling links.
    find "$dst" -maxdepth 1 -type l -delete
    find "$src" -mindepth 2 -maxdepth 2 -type f -name '*_DEM.tif' \
        -exec ln -sf -t "$dst" {} +
    echo "entrypoint: linked $(find "$dst" -maxdepth 1 -type l | wc -l) tiles into $dst"
done

exec "$@"
