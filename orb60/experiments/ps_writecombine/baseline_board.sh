#!/bin/sh
# A short, reversible microbenchmark. Never run while a network client is active.
set -eu
binary=/tmp/orb60-wc-ddr-bench-arm
pidfile=/tmp/orb60-150/server.pid
test -x "$binary"
test -r "$pidfile"
old=$(cat "$pidfile")
case "$old" in ''|*[!0-9]*) echo invalid-server-pid; exit 1;; esac
old_exe=$(readlink "/proc/$old/exe")
case "$old_exe" in
    /tmp/orb60-server-pipeline|/var/volatile/tmp/orb60-server-pipeline) ;;
    *) echo unexpected-server-executable; exit 1;;
esac
# Restrict the experiment to the exact previously inspected pipeline command.
tr '\000' '\n' < "/proc/$old/cmdline" > /tmp/orb60-wc-prior-args
printf '%s\n' /tmp/orb60-server-pipeline --uio /dev/uio0 --profile --pipeline > /tmp/orb60-wc-expected-args
cmp /tmp/orb60-wc-prior-args /tmp/orb60-wc-expected-args
if awk '$4 == "01" && $2 ~ /:15E0$/ {active=1} END {exit !active}' /proc/net/tcp /proc/net/tcp6; then
    echo active-feature-client-refusing-test
    exit 1
fi
/tmp/orb60-150/board-probe --loaded
restore() {
    previous_status=$?
    trap - EXIT HUP INT TERM
    sh /tmp/orb60-switch-server.sh /tmp/orb60-server-pipeline /tmp/orb60-pipeline-wc-restored.log --profile --pipeline || exit 1
    exit "$previous_status"
}
# Set the trap before the stop so failed tests cannot leave the server stopped.
trap restore EXIT HUP INT TERM
kill -TERM "$old"
for attempt in 1 2 3 4 5; do
    test -e "/proc/$old/exe" || break
    sleep 1
done
test ! -e "/proc/$old/exe"
"$binary" /dev/uio0 24 32768
"$binary" /dev/uio0 24 691200
echo LEGACY_DEVICE_MAPPING_MICROBENCH_PASS
