#!/bin/sh
# Resume a finite real-camera test against an explicitly installed camera map.
set -eu
camera_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
camera_root=$(CDPATH= cd -- "$camera_script/../../.." && pwd)
camera_desktop=0
camera_diagnostic=0
if test "${1:-}" = --desktop; then camera_desktop=1; shift; fi
if test "${1:-}" = --diagnostic; then camera_diagnostic=1; shift; fi
camera_install=${1:?installed camera RESULT.json required}
camera_frames=${2:-3600}
case "$camera_frames" in ''|*[!0-9]*) exit 64;; esac
test "$camera_frames" -ge 1 && test "$camera_frames" -le 36000
test -x "$camera_root/.venv_dpu/bin/python"
camera_release=$("$camera_root/.venv_dpu/bin/python" - "$camera_install" "$camera_root" "$camera_diagnostic" <<'PY'
from pathlib import Path
import hashlib,json,re,sys
p=Path(sys.argv[1]);root=Path(sys.argv[2]);r=json.loads(p.read_text())
source=r['source'];diagnostic=source.get('diagnostic_only',False)
if (r['status']!='ACTUAL_NATIVE_7015_NETWORK_MAP_IMPORT_ROUNDTRIP_PASS' or
    r['input_mode']!='live_camera' or type(diagnostic) is not bool or
    r.get('diagnostic_only',False)!=diagnostic or
    source.get('format')!=('KV260_LIVE_CAMERA_DIAGNOSTIC_SOURCE_V1' if diagnostic else 'KV260_LIVE_CAMERA_SOURCE_V1')):
    raise ValueError('An explicitly imported camera map is required')
if diagnostic and sys.argv[3]!='1':raise ValueError('Diagnostic camera map requires --diagnostic; stability was not accepted')
camera=root/'sources/orb60/kv260/config/camera_usb_20261103/camera_orb.csv'
h=hashlib.sha256(camera.read_bytes()).hexdigest()
if r['calibration_sha256']!=h or source['camera_sha256']!=h:raise ValueError('Installed map and current camera differ')
if not re.fullmatch('/opt/orb-demo/kv260_network_camera_[A-Za-z0-9_]+',r['release']):raise ValueError('Invalid release')
if not re.fullmatch('[a-f0-9]{64}',r['version']):raise ValueError('Invalid map version')
print(r['release'])
PY
)
mkdir -p "$camera_root/camera_localization_sessions"
camera_session=$(mktemp -d "$camera_root/camera_localization_sessions/localization-XXXXXX")
cp "$camera_install" "$camera_session/installation.json"
printf '%s\n' '使用已有摄像头地图定位；不会重新建图。' '请对准扫描过的区域，待识别后缓慢移动。'
if test "$camera_diagnostic" = 1; then
    printf '%s\n' '本地图用于联调，原建图稳定性检查未通过；本轮结果单独保存。'
fi
printf '最多 %s 帧，记录目录：%s\n' "$camera_frames" "$camera_session"
cd "$camera_root/sources"
camera_code=0
bash orb60/kv260/depth/runtime_exec.sh .. python -m orb60.kv260.run_7015_network_localization \
    --root .. --connection orb60/kv260/config/camera_session_connection.example.json \
    --release "$camera_release" --endpoint '[fe80::20a:35ff:fe00:122%eth0]:5605' \
    --mode live_camera --frames "$camera_frames" \
    --camera orb60/kv260/config/camera_usb_20261103/camera_orb.csv \
    --source-camera orb60/kv260/config/camera_usb_20261103/camera_source.csv \
    --library "$camera_root/camera_ingest_20261103_a/kv_native_b/liborb60_v4l2.so" \
    --output "$camera_session/run" || camera_code=$?
"$camera_root/.venv_dpu/bin/python" - "$camera_session" "$camera_code" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);installed=json.loads((p/'installation.json').read_text())
f=p/'run/RESULT.json';result=json.loads(f.read_text()) if f.is_file() else {}
version=result.get('hardware',{}).get('map_version')
bound=version==installed['version']
r=dict(status=result.get('status','FAILED_BEFORE_RESULT'),exit_code=int(sys.argv[2]),
       map_version_matches_installation=bound,mapping_stability_accepted=not installed.get('diagnostic_only',False),
       full_camera_chain_accepted=False,physical_single_cable_tested=False)
if not bound:r['status']='FAILED_MAP_BINDING'
(p/'SELECTION_RESULT.json').write_text(json.dumps(r,indent=2)+'\n')
print('本轮状态：'+r['status']+'；记录：'+str(f))
if not bound:raise SystemExit(1)
PY
if test "$camera_desktop" = 1; then printf '按回车关闭终端。'; read -r camera_done || :; fi
exit "$camera_code"
