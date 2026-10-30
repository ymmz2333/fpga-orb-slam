#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
trap 'bash "$experiment_root/scripts/temporary_swap.sh" off' EXIT
bash "$experiment_root/scripts/temporary_swap.sh" on
ORB_PHASE=a2 bash "$experiment_root/scripts/apply_patches.sh"
bash "$experiment_root/scripts/build_orbslam3.sh"
bash "$experiment_root/scripts/temporary_swap.sh" off
python3 "$experiment_root/scripts/preflight_a2.py"
python3 "$experiment_root/scripts/test_a2_analysis.py"
suite="a2_state_$(date -u +%Y%m%dT%H%M%S)_$$"
bash "$experiment_root/scripts/smoke_a1.sh" "$suite"
python3 "$experiment_root/scripts/analyze_a2.py" "$experiment_root/runtime/smoke_a1_$suite" --expected-frames 24
echo 'A2_INSTRUMENTATION_PASS: synthetic only; EuRoC experiments require dataset/evo/cooling confirmation'
