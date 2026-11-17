#!/usr/bin/env bash

set -euo pipefail

if (( $# > 1 )); then
    echo "Usage: new.sh [name-without-spaces]" >&2
    exit 1
fi
name="${1:-}"
if [[ "$name" == */* || "$name" =~ [[:space:]] ]]; then
    echo "Error: workspace names cannot contain slashes or whitespace." >&2
    exit 1
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export LC_ALL=C
shopt -s nullglob

max=0
for entry in "$PWD"/*; do
    if [[ -d "$entry" && ! -L "$entry" && "${entry##*/}" =~ ^[0-9][0-9](-.+)?$ ]]; then
        base="${entry##*/}"
        num=$((10#${base:0:2}))
        if (( num > max )); then
            max=$num
        fi
    fi
done

if (( max >= 99 )); then
    echo "Error: prefix 99 is already in use. Renumber to close gaps or remove a workspace first." >&2
    exit 1
fi

next=$(printf '%02d' "$((max + 1))")
new_dir="$PWD/$next"
if [[ -n "$name" ]]; then
    new_dir+="-$name"
fi
if [[ -e "$new_dir" || -L "$new_dir" ]]; then
    printf "Error: '%s' already exists.\n" "$new_dir" >&2
    exit 1
fi
mkdir -- "$new_dir"
printf 'Created: %s\n' "$new_dir"
