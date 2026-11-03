#!/bin/sh
# Manual mapping stop; automatic latest-map handoff and continuous localization.
set -eu
manual_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
manual_root=$(CDPATH= cd -- "$manual_script/../../.." && pwd)
test -f "$manual_root/manual_camera_system.json"
test -f "$manual_root/manual_camera_connection.json"
manual_existing=
if test -f "$manual_root/manual_latest_map.json"; then
    manual_existing=$("$manual_root/.venv_gui/bin/python" - "$manual_root/manual_latest_map.json" <<'PY'
import json,sys
from pathlib import Path
p=Path(json.loads(Path(sys.argv[1]).read_text())['handoff'])
if not p.is_absolute() or not (p/'HANDOFF.json').is_file():raise ValueError('Invalid saved map selection')
print(p)
PY
)
elif test -f "$manual_root/camera_motion_handoff_20261103_a/HANDOFF.json"; then
    manual_existing="$manual_root/camera_motion_handoff_20261103_a"
fi
cd "$manual_root/sources"
if test -n "$manual_existing"; then set -- --existing-map "$manual_existing" "$@"; fi
exec "$manual_root/.venv_gui/bin/python" -m orb60.kv260.manual_gui \
    --root "$manual_root" --config "$manual_root/manual_camera_system.json" \
    --connection "$manual_root/manual_camera_connection.json" \
    --library "$manual_root/camera_ingest_20261103_a/kv_native_b/liborb60_v4l2.so" "$@"
