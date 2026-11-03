#!/usr/bin/env bash
# Native VAI 2.5 build for the board's Python 3.10 ABI, installed privately.
# Does not load firmware, modify boot files, or replace system runtime libraries.
set -euo pipefail
root=$(realpath "${1:?Usage: build_board_runtime.sh PROJECT_ROOT}")
src="$root/vendor/vai25_runtime_source"
prefix="$root/runtime_vai25"
build="$root/build_vai25"
run_name="${2:-vai25_runtime_build}"
[[ "$run_name" =~ ^[A-Za-z0-9_-]+$ ]] || exit 2
run="$root/runs/$run_name"
test ! -e "$run/state.json" || { echo 'Use a fresh run name; prior evidence is retained' >&2;exit 3; }
jobs="${3:-2}"
[[ "$jobs" =~ ^[12]$ ]] || exit 2
resume_from="${4:-unilog}"
[[ "$resume_from" =~ ^(unilog|vart|library)$ ]] || exit 2
if test "$jobs" = 2 && test "$(awk '/MemAvailable:/{print $2}' /proc/meminfo)" -lt 2097152; then
    echo 'Two compiler jobs require at least 2 GiB currently available RAM' >&2;exit 3
fi
mkdir -p "$prefix" "$build" "$run"
test "$(uname -m)" = aarch64
test "$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')" = 3.10
if pgrep -x cc1plus >/dev/null; then
    echo 'Another native C++ compiler is active; finish the PS build first' >&2;exit 3
fi
command -v protoc >/dev/null
pkg-config --exists libglog json-c
test -f /usr/include/uuid/uuid.h || { echo 'Missing uuid-dev (required by XRT headers)' >&2;exit 3; }
test -f "$src/src/Vitis-AI-Runtime/VART/xir/CMakeLists.txt"
test -f "$src/src/Vitis-AI-Library/graph_runner/CMakeLists.txt"
if test -f "$run/pid" && kill -0 "$(cat "$run/pid")" 2>/dev/null; then
    echo 'Runtime compiler already running' >&2;exit 3
fi
printf '%s\n' "$$" > "$run/pid"
printf '{"status":"RUNNING","pid":%s}\n' "$$" > "$run/state.json"
export KV260_RUNTIME_RUN="$run"
finish() {
    code="$?"
    KV260_RUNTIME_EXIT="$code" python3 - <<'PY'
import json,os,time
from pathlib import Path
run=Path(os.environ['KV260_RUNTIME_RUN']);code=int(os.environ['KV260_RUNTIME_EXIT'])
record={'status':'IMPORT_PASS_HARDWARE_UNTESTED' if code==0 else 'BUILD_FAILED','exit_code':code,'finished_unix':time.time(),'firmware_loaded':False}
tmp=run/'state.tmp';tmp.write_text(json.dumps(record,indent=2)+'\n');tmp.replace(run/'state.json')
PY
    exit "$code"
}
trap finish EXIT
python3 "$(dirname "$0")/patch_runtime_metadata.py" "$src" "$run/source_metadata_patch.json"
python3 "$(dirname "$0")/patch_openssl_diagnostics.py" "$src" "$run/openssl_diagnostics"
python3 "$(dirname "$0")/patch_edge_xrt.py" "$src" "$run/xrt_edge_patch.json"
if ! test -x "$root/.venv_dpu/bin/python"; then python3 -m venv "$root/.venv_dpu"; fi
python="$root/.venv_dpu/bin/python"
"$python" -m pip install --no-index --find-links "$root/wheels" \
    numpy==1.26.4 scipy==1.14.1 opencv-python-headless==4.10.0.84 \
    av==14.2.0 pillow==11.0.0 PySide6-Essentials==6.8.0.2 \
    shiboken6==6.8.0.2 pyqtgraph==0.13.7 PyOpenGL==3.1.10 > "$run/python_dependencies.log" 2>&1
common=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_PREFIX_PATH="$prefix;/usr"
        -DCMAKE_INSTALL_RPATH="$prefix/lib" -DCMAKE_BUILD_WITH_INSTALL_RPATH=OFF
        -DBUILD_TEST=OFF -DBUILD_DOC=OFF -DBUILD_PYTHON=ON -DINSTALL_HOME=ON
        -DPYTHON_EXECUTABLE="$python" -DPython3_EXECUTABLE="$python"
        -DGIT_VERSION=c26eae36f034d5a2f9b2a7bfe816b8c43311a4f8)
export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$prefix/lib/python${PYTHONPATH:+:$PYTHONPATH}"
export XLNX_DISABLE_LOAD_XCLBIN=1
if test "$resume_from" = vart; then "$python" -c 'import xir,target_factory'; fi
if test "$resume_from" = library; then "$python" -c 'import xir,vart'; fi
started=0
for module in unilog xir target_factory vart; do
    if test "$module" = "$resume_from"; then started=1; fi
    if test "$started" = 0; then continue; fi
    printf 'VAI25_CONFIGURE %s\n' "$module"
    flags=()
    if test "$module" = vart; then flags=(-DENABLE_DPU_RUNNER=ON -DIS_EDGE=ON -DENABLE_SIM_RUNNER=OFF -DENABLE_CPU_RUNNER=OFF -U 'HAS_xclIPName2Index_*' -DCMAKE_CXX_STANDARD=17 -DCMAKE_CXX_STANDARD_REQUIRED=ON -DCMAKE_CXX_EXTENSIONS=OFF); fi
    cmake -S "$src/src/Vitis-AI-Runtime/VART/$module" -B "$build/$module" "${common[@]}" "${flags[@]}" > "$run/${module}_configure.log" 2>&1
    cmake --build "$build/$module" --parallel "$jobs" > "$run/${module}_build.log" 2>&1
    cmake --install "$build/$module" > "$run/${module}_install.log" 2>&1
done
printf 'VAI25_CONFIGURE graph_runner\n'
cmake -S "$src/src/Vitis-AI-Library" -B "$build/library" "${common[@]}" \
    -DDISABLE_ALL=ON -DENABLE_EFFICIENTDET_D2=OFF -DENABLE_TEXTMOUNTAIN=OFF \
    -DENABLE_OVERVIEW=OFF -DIS_EDGE=ON -DBUILD_SHARED_LIBS=ON > "$run/library_configure.log" 2>&1
cmake --build "$build/library" --parallel "$jobs" > "$run/library_build.log" 2>&1
query_module=$(find "$build/library/usefultools" -maxdepth 1 -name 'tools_extra_ops*.so' -print -quit)
test -n "$query_module"
if nm -D --undefined-only "$query_module" | grep -Eq '[[:space:]]xclRead$'; then
    echo 'Stale PCIe register reader remains after native edge configure; check board clock/object timestamps' >&2
    exit 3
fi
nm -D --undefined-only "$query_module" | grep -Eq '[[:space:]]xclRegRead$'
cmake --install "$build/library" > "$run/library_install.log" 2>&1
bash "$(dirname "$0")/build_ps_ops.sh" "$root" "$run/model_ps_ops"
"$python" - <<'PY' | tee "$run/import_check.json"
import json,sys,xir,vart
from vitis_ai_library import GraphRunner
print(json.dumps({'status':'NATIVE_PYTHON_ABI_IMPORT_PASS','python':sys.version,'xir':xir.__file__,'vart':vart.__file__,'GraphRunner':str(GraphRunner),'dpu_execution_verified':False},indent=2))
PY
