#!/bin/bash
# Serialized RK-only software build. No changes to PL, map, service or GUI session.
set -euo pipefail
root=$(cd -- "$1" && pwd)
stage="$root/tracking_diagnostics_20261026"
workspace="$root/workspace"
source="$root/rk_source"
export PYTHONPATH="$workspace${PYTHONPATH:+:$PYTHONPATH}"
test "$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)" -ge 1536
if pgrep -x cc1plus >/dev/null || pgrep -x mono_bridge >/dev/null || pgrep -f '^.*/demo_bin/mono_bridge_fastview2( |$)' >/dev/null; then
    echo 'Another compiler or mapper is running; no build/deployment performed' >&2;exit 1
fi
mkdir -p "$stage/backup" "$stage/test_output" "$stage/lib" "$stage/bin"
test ! -f "$stage/DEPLOYED.json"
cp -n "$source/lib/libORB_SLAM3.so" "$stage/backup/libORB_SLAM3.so"
cp -n "$root/rk_build/demo_bin/mono_bridge_fastview2" "$stage/backup/mono_bridge_fastview2"
cp -n "$root/rk.local.json" "$stage/backup/rk.local.json"
cp -n "$source/src/Tracking.cc" "$stage/backup/Tracking.cc"
cp -n "$source/src/ORBmatcher.cc" "$stage/backup/ORBmatcher.cc"
cp -n "$source/Examples/Monocular/mono_bridge.cc" "$stage/backup/mono_bridge.cc"
cp "$workspace/orb60/demo_bridge/rk/BridgeTrackingDiagnostics"*.h "$source/include/"
env -u LD_LIBRARY_PATH g++ -std=c++14 -O2 -pthread -I"$source/include" "$workspace/orb60/demo_bridge/tests/test_tracking_diagnostics.cpp" -o "$stage/bin/test_tracking_diagnostics"
test_output=$(mktemp -d "$stage/test_output/test.XXXXXX")
"$stage/bin/test_tracking_diagnostics" "$test_output" > "$stage/selftest.log"
env -u LD_LIBRARY_PATH python3 - "$test_output" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);files=sorted(p.glob('*.jsonl'))
assert len(files)==4 and files[0].name.endswith('000001.jsonl')
rows=[json.loads(line) for f in files for line in f.open()]
assert len(rows)==9001 and rows[-1]['source_frame_id']==12000
assert all(r['events_dropped']==0 and r['events'][0]['stage']=='tracking_exit' for r in rows)
print('TRACKING_DIAGNOSTICS_JSON_RETENTION_PASS',len(rows))
PY
env -u LD_LIBRARY_PATH python3 -m orb60.demo_bridge.patch_tracking_diagnostics "$source"
cp "$workspace/orb60/demo_bridge/rk/mono_bridge.cc" "$source/Examples/Monocular/mono_bridge.cc"
if ! cmake --build "$root/rk_build" --target mono_bridge_fastview2 -- -j1 > "$stage/build.log" 2>&1; then
    cp "$stage/backup/libORB_SLAM3.so" "$source/lib/libORB_SLAM3.so"
    echo 'BUILD_FAILED; previous runtime library restored; inspect build.log' >&2;exit 1
fi
cp "$source/lib/libORB_SLAM3.so" "$stage/lib/"
cp "$root/rk_build/demo_bin/mono_bridge_fastview2" "$stage/bin/"
env -u LD_LIBRARY_PATH python3 - "$root" "$stage" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
root,stage=map(Path,sys.argv[1:]);config=root/'rk.local.json'
# Commit only when no mapping session owns the previous binary.
import urllib.request
status=json.load(urllib.request.urlopen('http://127.0.0.1:5610/status',timeout=5))
assert status['state'] not in ('MAPPING','FINALIZING','INSTALLING') and not status['busy'],status['state']
executable=stage/'run_mapper.sh'
executable.write_text('#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport LD_LIBRARY_PATH="$root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\nexec "$root/bin/mono_bridge_fastview2" "$@"\n')
executable.chmod(0o755)
cfg=json.loads(config.read_text());cfg['executable']=str(executable)
temp=config.with_suffix('.json.diag-new');temp.write_text(json.dumps(cfg,indent=2)+'\n');os.replace(temp,config)
proof={'status':'DEPLOYED','policy':'Observation only; no matching, pose or map thresholds changed','binary_sha256':hashlib.sha256((stage/'bin/mono_bridge_fastview2').read_bytes()).hexdigest(),'library_sha256':hashlib.sha256((stage/'lib/libORB_SLAM3.so').read_bytes()).hexdigest(),'executable':str(executable)}
(stage/'DEPLOYED.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
PY
systemctl --user restart orb-demo-controller.service
systemctl --user is-active --quiet orb-demo-controller.service
echo TRACKING_DIAGNOSTICS_DEPLOYMENT_COMPLETE
