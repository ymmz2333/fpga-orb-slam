#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
python3 "$experiment_root/scripts/environment_snapshot.py"
bash "$experiment_root/scripts/temporary_swap.sh" on
trap 'bash "$experiment_root/scripts/temporary_swap.sh" off' EXIT
bash "$experiment_root/scripts/fetch_sources.sh"
bash "$experiment_root/scripts/apply_patches.sh"
bash "$experiment_root/scripts/build_opencv.sh"
bash "$experiment_root/scripts/build_pangolin.sh"
bash "$experiment_root/scripts/build_orbslam3.sh"
bash "$experiment_root/scripts/diagnose_opencv.sh"
bash "$experiment_root/scripts/verify_a1_runtime.sh"
bash "$experiment_root/scripts/temporary_swap.sh" off
python3 "$experiment_root/scripts/environment_snapshot.py" --stem environment-final
python3 "$experiment_root/scripts/collect_a1_evidence.py"
