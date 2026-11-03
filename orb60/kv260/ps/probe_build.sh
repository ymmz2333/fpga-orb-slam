#!/usr/bin/env bash
set -eu
free -m
ps -eo pid,comm,pcpu,rss,wchan:24 --sort=-pcpu | head -8
find /home/ubuntu/kv260_orb_20261102/build/CMakeFiles/ORB_SLAM3.dir -name '*.o' -printf '%f\n' | tail -5
for node in /sys/class/thermal/thermal_zone*/temp; do
    if test -r "$node"; then printf '%s ' "$node"; cat "$node"; fi
done
