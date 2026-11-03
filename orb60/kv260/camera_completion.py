"""No-map camera input can drain cleanly, but cannot pass mapping/dense gates."""
import json
from pathlib import Path


def uninitialized_camera(config,root,seen,blocks):
    if not config.get('allow_uninitialized_camera_completion',False):return False
    if config.get('input_kind')!='live_camera':
        raise ValueError('Empty-camera completion is exclusive to explicit live camera input')
    root=Path(root)
    state=json.loads((root/'camera_mapping_status.json').read_text())
    if state.get('status')!='INPUT_DRAINED_NO_MAP_INITIALIZED':return False
    mapping=json.loads((root/'network_mapping.json').read_text())
    if (state.get('mapping_verified') is not False or mapping.get('source_input')!='actual_KV260_V4L2_camera' or
        mapping.get('status')!='CAMERA_TRACKING_DRAINED_EXPORT_PENDING' or mapping.get('frames',0)<=0 or
        mapping.get('valid_poses')!=0 or mapping.get('selected_keyframes')!=0 or mapping.get('cpu_orb_calls')!=0 or
        not (root/'CAMERA_INPUT_COMPLETE').is_file() or (root/'NATIVE_COMPLETE').exists() or
        (root/'tracking/map/EXPORT_COMPLETE').exists() or seen or blocks or
        any((root/'dense/color_poses').glob('f*.json'))):
        raise ValueError('No-map camera completion contradicted by native or geometry evidence')
    return True
