#!/bin/sh
# Finite live-camera session; existing current-boot hardware is checked only.
set -eu
camera_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
camera_root=$(CDPATH= cd -- "$camera_script/../../.." && pwd)
camera_desktop=0
if test "${1:-}" = --desktop; then camera_desktop=1; shift; fi
camera_frames=${1:-600}
case "$camera_frames" in ''|*[!0-9]*) echo '帧数必须是正整数。' >&2; exit 64;; esac
test -x "$camera_root/.venv_dpu/bin/python"
mkdir -p "$camera_root/camera_sessions"
camera_session=$(mktemp -d "$camera_root/camera_sessions/session-XXXXXX")
camera_output="$camera_session/run"
printf '%s\n' '摄像头建图与彩色点云' '出现等待初始化时，请缓慢平移摄像头，避免只在原地转动。' 
printf '本轮最多处理 %s 帧；结果保存在 %s\n' "$camera_frames" "$camera_session"
printf '%s\n' '正在检查加速器并加载建图程序，稍后会出现地图窗口。'
cd "$camera_root/sources"
camera_code=0
bash orb60/kv260/depth/runtime_exec.sh .. python -m orb60.kv260.run_camera_two_board_session \
    --config orb60/kv260/config/camera_system.example.json \
    --connection orb60/kv260/config/camera_session_connection.example.json \
    --library "$camera_root/camera_ingest_20261103_a/kv_native_b/liborb60_v4l2.so" \
    --output "$camera_output" --frames "$camera_frames" --localization-frames "$camera_frames" || camera_code=$?
"$camera_root/.venv_dpu/bin/python" - "$camera_output" <<'PY'
from pathlib import Path
import json,sys
path=Path(sys.argv[1])/'session.json'
if not path.is_file():
    print('启动检查未通过，请查看上方错误；没有宣称建图完成。')
else:
    r=json.loads(path.read_text());status=r.get('status')
    if status=='CAMERA_INPUT_COMPLETE_NO_MAP_NO_HANDOFF':
        print('相机、7015前端和GPU显示已结束；本轮尚未初始化地图，没有生成彩色地图。')
    elif status=='ACTUAL_KV260_CAMERA_MAPPING_HANDOFF_7015_LOCALIZATION_PASS':
        print('本轮已完成摄像头建图、DPU彩色点云、地图交接及7015实际摄像头定位。')
    else:
        print('本轮未通过完整检查，已保存实际状态：'+str(status))
    print('详细记录：'+str(path))
PY
if test "$camera_desktop" = 1; then printf '按回车关闭终端。'; read -r camera_done || :; fi
exit "$camera_code"
