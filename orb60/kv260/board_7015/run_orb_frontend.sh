#!/bin/sh
# Explicit physical PL frontend; owned by the KV260 SSH supervisor or a terminal.
# No bitstream loading, synthetic results, recovery, or detached daemon.
set -eu
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-terminal}
case "$mode" in terminal|--stdin-control) ;; *) echo 'Use terminal or --stdin-control' >&2; exit 64;; esac
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
cd "$release"
sha256sum -c SHA256SUMS
lock=/run/orb-demo.lock
mkdir "$lock"
child=
cleanup() {
    trap - EXIT HUP INT TERM
    if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
    rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
boot=$(cat /proc/sys/kernel/random/boot_id)
mkdir -p "$release/runs"
run=$(mktemp -d "$release/runs/frontend-$boot-XXXXXX")
"$release/bin/orb60-server" --uio /dev/uio0 --pipeline --profile \
    </dev/null >"$run/stdout.log" 2>"$run/stderr.log" &
child=$!
printf '%s\n' "$child" >"$run/child.pid"
printf 'ORB_FRONTEND_RUN=%s\n' "$run"
attempt=0
while ! grep -q '^ORB60_SERVER_READY port=5600 simulated=0$' "$run/stdout.log"; do
    kill -0 "$child" 2>/dev/null || { tail -n 6 "$run/stderr.log" >&2; exit 1; }
    attempt=$((attempt+1))
    test "$attempt" -lt 100 || { echo 'Physical ORB frontend did not become ready' >&2; exit 1; }
    sleep .1
done
printf 'ORB_FRONTEND_READY=physical\n'
requested=0
if test "$mode" = --stdin-control; then
    # EOF also stops this owned child. The controller keeps SSH stdin open.
    if IFS= read -r command; then
        test "$command" = STOP || { echo 'Expected STOP' >&2; exit 64; }
        # A dead server must not be reported as a successful requested stop.
        IFS=' ' read -r child_pid child_name child_state remaining <"/proc/$child/stat"
        test "$child_state" != Z || { echo 'Frontend exited before STOP' >&2; exit 1; }
        requested=1
    fi
    kill -TERM "$child" 2>/dev/null || :
fi
rc=0
wait "$child" || rc=$?
child=
printf '%s\n' "$rc" >"$run/exit_code"
printf '%s\n' "$requested" >"$run/controlled_stop"
tail -n 4 "$run/stdout.log"
test ! -s "$run/stderr.log" || tail -n 6 "$run/stderr.log"
# The retained server has the default SIGTERM disposition. Its actual signal
# exit is kept above; only an explicit STOP of a live owned child is normal.
if test "$requested" = 1 && test "$rc" = 143; then exit 0; fi
exit "$rc"
