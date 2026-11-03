#!/usr/bin/env bash
# Read-only first step after reconnecting. Never start another compiler here.
set -euo pipefail
root="$HOME/kv260_orb_20261102"
printf '=== platform ===\n'
uname -a
free -m
printf '\n=== existing build processes ===\n'
ps -eo pid,ppid,comm,pcpu,rss,args | grep -E '[c]c1plus|[c]make --build|[m]ono_kv260' || true
printf '\n=== build products ===\n'
for path in "$root/build/bin/mono_kv260" "$root/build/lib/libORB_SLAM3.so"; do
    if test -f "$path"; then ls -lh "$path"; sha256sum "$path"; fi
done
printf '\n=== compiled translation units ===\n'
if test -d "$root/build/CMakeFiles/ORB_SLAM3.dir"; then
    find "$root/build/CMakeFiles/ORB_SLAM3.dir" -name '*.o' -printf '%P\n' | sort
fi
printf '\n=== temporary swap, if any ===\n'
cat /proc/swaps
printf '\n=== display session ===\n'
loginctl list-sessions --no-legend
