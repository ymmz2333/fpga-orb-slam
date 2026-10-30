#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
pidfile=/run/zynq-slam.lock/pid
running() { test -r "$pidfile" && kill -0 "$(cat "$pidfile")" 2>/dev/null; }
case "${1:-status}" in
    start)
        if running; then echo 'Already running'; exit 0; fi
        test ! -d /run/zynq-slam.lock || { echo 'Stale lock; inspect processes before removal' >&2; exit 1; }
        sh "$release/scripts/bind_wc.sh"
        nohup sh "$release/scripts/run_hdmi.sh" > /run/zynq-slam-service.log 2>&1 < /dev/null &
        sleep 1
        running
        echo "RUNNING pid=$(cat "$pidfile")"
        ;;
    stop)
        if running; then
            kill -TERM "$(cat "$pidfile")"
            n=0
            while running && test "$n" -lt 15; do sleep 1; n=$((n+1)); done
            if running; then echo 'Application did not finish shutdown' >&2; exit 1; fi
        fi
        echo STOPPED
        ;;
    status)
        if running; then echo "RUNNING pid=$(cat "$pidfile")"; else echo STOPPED; fi
        test ! -L /opt/zynq-slam/runs/latest || readlink /opt/zynq-slam/runs/latest
        ;;
    mapping|localization|save|reset)
        running
        case "$1" in mapping) key=m;;localization) key=l;;save) key=s;;reset) key=r;;esac
        printf '%s' "$key" > /run/zynq-slam.lock/control
        echo "QUEUED $1"
        ;;
    *) echo 'Usage: zslamctl.sh start|stop|status|mapping|localization|save|reset' >&2; exit 2;;
esac
