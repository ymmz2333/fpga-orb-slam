#!/usr/bin/env bash
# Run only the requested command with the private native VAI 2.5 runtime.
# No firmware loading, system library replacement, or persistent environment edits.
set -euo pipefail
root=$(realpath "${1:?Usage: runtime_exec.sh PROJECT_ROOT COMMAND [ARGS...]}")
shift
test "$#" -gt 0
test -x "$root/.venv_dpu/bin/python"
test -d "$root/runtime_vai25/lib/python"
export PATH="$root/.venv_dpu/bin:$root/runtime_vai25/bin:$PATH"
export LD_LIBRARY_PATH="$root/runtime_vai25/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$root/runtime_vai25/lib/python${PYTHONPATH:+:$PYTHONPATH}"
# VART's device-handle constructor otherwise loads its default xclbin, even
# during xdputil query. Require the already installed hardware explicitly.
export XLNX_DISABLE_LOAD_XCLBIN=1
exec "$@"
