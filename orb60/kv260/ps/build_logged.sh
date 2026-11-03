#!/usr/bin/env bash
# Foreground native build with durable exit status, even if the SSH client disconnects.
set -euo pipefail
src=$(realpath "${1:?Usage: build_logged.sh SOURCE BUILD RUN}")
build=$(realpath -m "${2:?}")
run=$(realpath -m "${3:?}")
mkdir -p "$run"
if test -f "$run/pid"; then
    previous=$(cat "$run/pid")
    if kill -0 "$previous" 2>/dev/null && tr '\0' ' ' < "/proc/$previous/cmdline" | grep -q 'build_logged.sh'; then
        echo 'Existing native build still running' >&2; exit 3
    fi
fi
printf '%s\n' "$$" > "$run/pid"
export KV260_BUILD_RUN="$run" KV260_BUILD_SOURCE="$src" KV260_BUILD_DIR="$build"
record() {
    code="$?"
    KV260_BUILD_EXIT="$code" python3 - <<'PY'
import hashlib,json,os,time
from pathlib import Path
run=Path(os.environ['KV260_BUILD_RUN']);src=Path(os.environ['KV260_BUILD_SOURCE']);build=Path(os.environ['KV260_BUILD_DIR'])
code=int(os.environ['KV260_BUILD_EXIT'])
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
files=[src/'CMakeLists.txt',src/'src/System.cc',src/'src/Map.cc',src/'Examples/Monocular/mono_kv260.cc']
if code==0:files += [build/'bin/mono_kv260',build/'lib/libORB_SLAM3.so']
record=dict(status='SUCCEEDED' if code==0 else 'FAILED',exit_code=code,finished_unix=time.time(),
            source=str(src),build=str(build),sha256={str(p):sha(p) for p in files if p.is_file()})
temporary=run/'state.tmp';temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(run/'state.json')
PY
    exit "$code"
}
trap record EXIT
printf '{"status":"RUNNING","pid":%s}\n' "$$" > "$run/state.json"
printf 'KV260_NATIVE_BUILD_STARTED pid=%s log=%s\n' "$$" "$run/console.log"
bash "$(dirname "$0")/build.sh" "$src" "$build" > "$run/console.log" 2>&1 || exit "$?"
file "$build/bin/mono_kv260" "$build/lib/libORB_SLAM3.so" | tee "$run/architecture.txt"
ldd "$build/bin/mono_kv260" > "$run/dependencies.txt"
if grep -q 'not found' "$run/dependencies.txt"; then cat "$run/dependencies.txt"; exit 4; fi
echo KV260_NATIVE_BUILD_AND_LINK_PASS
