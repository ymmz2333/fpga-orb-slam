#!/bin/sh
# Replace only the userspace server, after verifying both PL cores are idle.
set -eu
binary=$1
log=$2
shift 2
test -x "$binary"
/tmp/orb60-150/board-probe --loaded
pidfile=/tmp/orb60-150/server.pid
if test -f "$pidfile"; then
    old=$(cat "$pidfile")
    if test -z "$old"; then
        # Early bringup launched without a reliable shell pidfile. Recover
        # only an exact known executable, never a broad process-name kill.
        for candidate in /proc/[0-9]*/exe; do
            executable=$(readlink "$candidate" || true)
            case "$executable" in
                /tmp/orb60-150/orb60-server-arm|/tmp/orb60-server-*|/var/volatile/tmp/orb60-150/orb60-server-arm|/var/volatile/tmp/orb60-server-*)
                    test -z "$old" || { echo multiple-orb60-servers; exit 1; }
                    old=${candidate%/exe};old=${old##*/};;
            esac
        done
    fi
    case "$old" in ''|*[!0-9]*) echo invalid-server-pid; exit 1;; esac
    if test -d "/proc/$old"; then
        tr '\000' ' ' < "/proc/$old/cmdline" | grep -q orb60-server
        kill -TERM "$old"
        for attempt in 1 2 3 4 5; do
            test -e "/proc/$old/exe" || break
            sleep 1
        done
        test ! -e "/proc/$old/exe"
    fi
fi
nohup "$binary" --uio /dev/uio0 "$@" > "$log" 2>&1 < /dev/null &
echo $! > "$pidfile"
sleep 1
cat "$log"
kill -0 "$(cat "$pidfile")"
echo ORB60_SERVER_SWITCH_PASS
