#!/bin/sh
# Software-only A/B against the unchanged SD baseline hardware.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
cd "$release"
sha256sum -c SHA256SUMS
chmod 755 bin/*
scratch=$(mktemp -d /tmp/slam60-selftest.XXXXXX)
./bin/test-zslam "$scratch" > "$release/selftest.log" 2>&1
tail -n 10 "$release/selftest.log"
test "$(cat /sys/class/uio/uio0/version)" = wc1
sh "$baseline/scripts/zslamctl.sh" stop
restore() {
    rc=$?
    trap - EXIT INT TERM
    if test "$rc" = 0; then
        sh "$baseline/scripts/zslamctl.sh" start
    else
        # A failed PL call cannot be retried against possibly active DMA.
        echo 'EXPERIMENT_FAILED; rebooting the preserved SD baseline' >&2
        sync
        /sbin/reboot
    fi
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for pause in 0 50; do
    run=$release/poll-$pause
    test ! -e "$run"
    ./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
        --uio /dev/uio0 --hdmi-uio /dev/uio0 --calibration config/camera_handoff.csv \
        --import-map /opt/zynq-slam/data/handoff_map_20261023 \
        --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 \
        --target-fps 60 --orb-poll-us "$pause" --max-points 3000 --max-keyframes 16 \
        --frames 2273 --output "$run" > "$release/poll-$pause.log" 2>&1
    cat "$run/run.json" "$run/display.json"
    awk -F, 'NR>1 {n++;for(i=3;i<=8;i++)s[i]+=$i;for(i=17;i<=21;i++)s[i]+=$i} END {printf "MEAN_MS frames=%d capture=%.6f orb=%.6f slam=%.6f render=%.6f present=%.6f period=%.6f CPU_capture=%.6f CPU_orb=%.6f CPU_slam=%.6f CPU_render=%.6f CPU_present=%.6f\n",n,s[3]/n,s[4]/n,s[5]/n,s[6]/n,s[7]/n,s[8]/n,s[17]/n,s[18]/n,s[19]/n,s[20]/n,s[21]/n}' "$run/timing.csv"
done
echo POLL_AB_COMPLETED_BASELINE_WILL_RESUME
