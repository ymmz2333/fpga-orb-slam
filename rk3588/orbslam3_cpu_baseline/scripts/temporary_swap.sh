#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
swap_path="$experiment_root/runtime/build.swap"
case "${1:-on}" in
    on)
        if ! swapon --noheadings --show=NAME | grep -Fxq "$swap_path"; then
            if [[ ! -f "$swap_path" ]]; then
                sudo -n fallocate -l 8G "$swap_path"
                sudo -n chmod 600 "$swap_path"
                sudo -n mkswap "$swap_path"
            fi
            sudo -n swapon "$swap_path"
        fi
        ;;
    off)
        if swapon --noheadings --show=NAME | grep -Fxq "$swap_path"; then
            sudo -n swapoff "$swap_path"
        fi
        sudo -n rm -f -- "$swap_path"
        ;;
    *) printf 'Usage: %s on|off\n' "$0" >&2; exit 2 ;;
esac
swapon --show
