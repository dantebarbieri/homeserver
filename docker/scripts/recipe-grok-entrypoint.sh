#!/bin/sh

set -eu

data_dir="${RECIPES_DATA_DIR:-/data/recipes}"
seed_dir="/seed/recipes"

mkdir -p "$data_dir"

if [ -d "$seed_dir" ]; then
    recipe_count=$(find "$data_dir" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$recipe_count" = "0" ]; then
        echo "Seeding recipe data into $data_dir"
        cp -a "$seed_dir"/. "$data_dir"/
    fi
fi

exec "$@"
