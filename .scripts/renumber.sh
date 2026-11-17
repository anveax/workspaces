#!/usr/bin/env bash

set -euo pipefail

if (( $# > 0 )); then
    echo "Usage: renumber.sh" >&2
    exit 1
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export LC_ALL=C
shopt -s nullglob

valid=()
new_names=()
for entry in "$PWD"/*; do
    if [[ -d "$entry" && ! -L "$entry" && "${entry##*/}" =~ ^[0-9][0-9](-.+)?$ ]]; then
        valid+=("${entry##*/}")
    fi
done
if (( ${#valid[@]} == 0 )); then
    echo "No workspaces to renumber."
    exit 0
fi
if (( ${#valid[@]} > 99 )); then
    echo "Error: too many workspaces (${#valid[@]}, maximum 99)." >&2
    exit 1
fi

changes=false
for i in "${!valid[@]}"; do
    num=$(printf '%02d' "$((i + 1))")
    new_names+=("$num${valid[$i]:2}")
    if [[ "${valid[$i]}" != "${new_names[$i]}" ]]; then
        changes=true
    fi
done
if ! $changes; then
    echo "Directories are already correctly numbered."
    exit 0
fi

for target in "${new_names[@]}"; do
    if [[ -e "$target" || -L "$target" ]]; then
        is_source=false
        for old in "${valid[@]}"; do
            if [[ "$target" == "$old" ]]; then
                is_source=true
                break
            fi
        done
        if ! $is_source; then
            printf "Error: target '%s' already exists.\n" "$target" >&2
            exit 1
        fi
    fi
done

printf 'Workspaces: %s\nPlanned renames:\n' "$PWD"
for i in "${!valid[@]}"; do
    printf '  %s → %s\n' "${valid[$i]}" "${new_names[$i]}"
done
while true; do
    if ! read -r -p 'Proceed with renumbering? (yes/no): ' answer; then
        echo "Operation cancelled (no confirmation received)."
        exit 1
    fi
    case "$answer" in
        [Yy]es) break ;;
        [Nn]o) echo "Operation cancelled."; exit 0 ;;
        *) echo "Please answer yes or no." ;;
    esac
done

stage=$(mktemp -d "$PWD/.renumber.XXXXXXXX")
placing=false
completed=false
cleanup_renumber() {
    local status=$? i failed=false
    trap - EXIT
    if ! $completed; then
        if $placing; then
            for i in "${!valid[@]}"; do
                if [[ ! -d "$stage/${valid[$i]}" ]]; then
                    if ! mv -- "${new_names[$i]}" "$stage/${valid[$i]}"; then
                        failed=true
                    fi
                fi
            done
        fi
        if ! $failed; then
            for i in "${!valid[@]}"; do
                if [[ -d "$stage/${valid[$i]}" ]]; then
                    if ! mv -- "$stage/${valid[$i]}" "${valid[$i]}"; then
                        failed=true
                    fi
                fi
            done
        fi
        if $failed; then
            printf 'Error: rollback incomplete; recover remaining workspaces from %s\n' "$stage" >&2
        else
            echo "Renumbering failed; original names restored." >&2
        fi
    fi
    if ! $failed; then
        rmdir -- "$stage"
    fi
    exit "$status"
}
trap cleanup_renumber EXIT

for i in "${!valid[@]}"; do
    mv -- "${valid[$i]}" "$stage/${valid[$i]}"
done
placing=true
for i in "${!valid[@]}"; do
    mv -- "$stage/${valid[$i]}" "${new_names[$i]}"
done
completed=true
echo "Done."
