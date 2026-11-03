#!/usr/bin/env bash
# Bounded, read-only board inventory. No firmware loads or driver installation.
set -u
printf '=== current applications ===\n'
command -v xmutil >/dev/null && xmutil listapps 2>&1
printf '\n=== compute and graphics nodes ===\n'
ls -l /dev/dpu* /dev/mali* /dev/dri/* /dev/accel/* /dev/zocl* 2>/dev/null || true
printf '\n=== user access ===\n'
id
printf '\n=== runtime tools ===\n'
for tool in xdputil xrt-smi xbutil glxinfo eglinfo; do command -v "$tool" || true; done
printf '\n=== installed runtime packages ===\n'
dpkg-query -W -f='${binary:Package}\t${Version}\n' 2>/dev/null | grep -Ei 'xrt|vart|xir|vitis|mali|mesa|libegl|libgles|glmark|glx' | head -60 || true
printf '\n=== kernel graphics/FPGA modules ===\n'
lsmod | grep -Ei 'mali|lima|panfrost|drm|zocl|dpu|fpga' || true
printf '\n=== graphics libraries ===\n'
ldconfig -p | grep -Ei 'lib(EGL|GLESv2|Mali|vart|xir)' | head -30 || true
printf '\n=== display sessions ===\n'
loginctl list-sessions --no-legend
printf '\n=== local Python runtimes ===\n'
for py in /usr/bin/python3 "$HOME/kv260_orb_20261102/.venv_gui/bin/python" "$HOME/kv260_orb_20261102/.venv_dpu/bin/python"; do
    test -x "$py" || continue
    if [[ "$py" == */.venv_dpu/* ]]; then
        PYTHONPATH="$HOME/kv260_orb_20261102/runtime_vai25/lib/python${PYTHONPATH:+:$PYTHONPATH}" \
        LD_LIBRARY_PATH="$HOME/kv260_orb_20261102/runtime_vai25/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$py" -c 'import sys,importlib.util;print(sys.executable,sys.version.split()[0]);print({k:bool(importlib.util.find_spec(k)) for k in ("xir","vart","vitis_ai_library","PySide6","cv2","numpy","scipy")})'
    else
        "$py" -c 'import sys,importlib.util;print(sys.executable,sys.version.split()[0]);print({k:bool(importlib.util.find_spec(k)) for k in ("xir","vart","vitis_ai_library","PySide6","cv2","numpy","scipy")})'
    fi
done
printf '\n=== DPU read-only query ===\n'
root="$HOME/kv260_orb_20261102"
if test -f "$root/runtime_vai25/bin/xdputil"; then
    timeout 20s bash "$root/sources/orb60/kv260/depth/runtime_exec.sh" "$root" python -m xdputil query 2>&1
elif command -v xdputil >/dev/null; then
    XLNX_DISABLE_LOAD_XCLBIN=1 timeout 20s xdputil query 2>&1
else echo 'XDPUTIL_NOT_INSTALLED'; fi
