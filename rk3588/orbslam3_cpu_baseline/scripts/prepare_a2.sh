#!/usr/bin/env bash
# Dataset is extracted on the PC and transferred over LAN. No board pip/download.
source "$(dirname -- "$0")/common.sh"
python3 "$experiment_root/scripts/preflight_a2.py"
python3 "$experiment_root/scripts/check_dataset_transfer.py" "${MH01_DATASET:-$HOME/data/euroc/MH_01_easy}"
python3 "$experiment_root/scripts/validate_mh01.py" "${MH01_DATASET:-$HOME/data/euroc/MH_01_easy}"
echo A2_PREPARATION_PASS
