"""Seal only a completed, stable real-camera map with actual DPU and Mali evidence.

Finite live capture is distinct from the whole saved-video source gate. The old
video gate is unchanged; a drained stationary camera cannot publish a map.
"""
import argparse
import json
import math
from pathlib import Path
from .run_network_system import load,digest,rows
from .run_camera_mapping import verify_input
from .map_continuity import audit
from .mapping_acceptance import evaluate
from .handoff_7015 import _package_verified_source


def stable_camera_source(run,camera,diagnostic=False,manual_latest=False):
    run,camera=Path(run).resolve(),Path(camera).resolve();control=run.with_name(run.name+'_control')
    result=load(control/'RESULT.json')
    accepted_status=result.get('status')=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS'
    diagnostic_status=(diagnostic or manual_latest) and result.get('status')=='FAILED_TARGET_GATES'
    if (not (accepted_status or diagnostic_status) or
        result.get('input')!='actual_KV260_USB3_camera' or result.get('frontend')!='actual7015_PL' or
        result.get('mapping')!='KV260_PS' or result.get('mapping_verified') is not accepted_status or
        result.get('hardware_inference_verified') is not True or result.get('gpu_hardware_verified') is not True):
        raise ValueError('Completed stable real-camera/DPU/Mali acceptance required; no saved-input substitution')
    if result.get('camera_sha256')!=digest(camera):raise ValueError('Camera handoff calibration differs from the actual run')
    count=result['frames_requested']
    manual=result.get('manual_control',False)
    if manual_latest and not manual:raise ValueError('Latest-map handoff requires an explicitly stopped manual run')
    if type(count)!=int or count<2 or (not manual and count>36000):raise ValueError('Complete finite or explicitly stopped manual camera run required')
    if manual and (result.get('manual_stop')!={'status':'OPERATOR_STOP_DRAINED','frames':count} or
                   load(run/'manual_stop.json')!=result['manual_stop']):
        raise ValueError('Manual source requires exact operator stop receipt')
    checked=verify_input(run,count)
    if checked!=result['camera_input'] or not checked['valid_poses'] or checked['native']['selected_keyframes']<1:
        raise ValueError('Actual camera input/PL evidence changed or no map initialized')
    if not (run/'NATIVE_COMPLETE').is_file() or not (run/'tracking/map/EXPORT_COMPLETE').is_file():
        raise ValueError('Camera native drain and final export required')
    tracking=rows(run/'tracking/frames.csv');first=checked['first_valid_frame']
    continuity=audit(tracking,(control/'native.log').read_text(errors='replace'))
    ratio=sum(int(r['pose_valid']) for r in tracking[first:])/len(tracking[first:])
    dense=result['dense'];native=checked['native']
    if (dense['status']!='COMPLETED' or not dense.get('hardware_inference_verified') or
        not dense.get('hardware_projection_verified')):
        raise ValueError('Actual camera DPU and PL point projection required')
    elapsed=(dense['completed_monotonic_ns']-native['started_monotonic_ns'])*1e-9
    if not math.isfinite(elapsed) or elapsed<=0:raise ValueError('Invalid camera geometry time interval')
    if native.get('source_input')!='actual_KV260_V4L2_camera' or native.get('gray_input')!='camera_original_Y':
        raise ValueError('Actual camera source and original luminance required')
    accepted=evaluate('stable_map_5fps',dict(valid_after_initialization=ratio,frames=count),continuity,
                      dict(all_geometry_fps=count/elapsed),profiling=False,kernel_tainted=result['kernel_tainted'],
                      last_pose_valid=bool(int(tracking[-1]['pose_valid'])))
    stability_accepted=accepted['status']=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS'
    if not stability_accepted:
        permitted={'Tracking stability below98% after initialization'}
        if manual_latest:permitted.add('Whole-video SLAM created multiple maps or its map creation record is missing')
        if (not (diagnostic or manual_latest) or not set(accepted['failed_gates'])<=permitted or
            result.get('failed_gates')!=accepted['failed_gates']):
            raise ValueError('Recomputed camera stability/speed gate failed')
    mid=int((run/'tracking/map/map_id.txt').read_text())
    if manual_latest:
        # ExportBridgeAtlas freezes Atlas::GetCurrentMap() after Shutdown. It is
        # the last active/updated map, not the largest ID or largest point cloud.
        if mid not in {m['map_id'] for m in continuity['maps_created']}:
            raise ValueError('Current exported map has no creation record')
        selected=[m for m in dense.get('maps',[]) if m['map_id']==mid]
        if len(selected)!=1 or selected[0]['points']<1:raise ValueError('Current map has no matching dense cloud')
    elif mid!=continuity['maps_created'][0]['map_id'] or not dense.get('maps') or any(m['map_id']!=mid or m['points']<1 for m in dense['maps']):
        raise ValueError('Camera sparse/dense export must use the only created map')
    worker=load(run/'dense/depth/worker.json');tasks=worker.get('frames',[])
    if (worker.get('backend')!='dpu' or not worker.get('hardware_inference_verified') or worker.get('hardware_driver')!='vivado' or
        worker.get('model_sha256')!=result.get('model_sha256') or not result.get('model_sha256') or
        len(tasks)!=native['selected_keyframes'] or len(tasks)!=len(dense['timings']) or any(t['reused'] for t in tasks)):
        raise ValueError('Selected camera keyframes require matching actual DPU receipts')
    update=load(run/'dense/blocks/final_pose_update.json')
    if update['map_id']!=mid or not update['accepted']:raise ValueError('Final camera dense pose update absent')
    for name in update['accepted']:
        if Path(name).name!=name:raise ValueError('Invalid camera point block name')
        meta=load(run/'dense/blocks'/(name+'.final.json'))
        if meta.get('map_id')!=mid or meta.get('geometry_backend')!='actual_kv260_pl_point_project':
            raise ValueError('Final camera point block requires actual same-map PL projection')
    from .frame_store import FrameStore
    store=FrameStore(run/'dense/rgb_cache');poses=list((run/'dense/color_poses').glob('f*.json'))
    if len(poses)!=len(tasks):raise ValueError('Camera keyframe/RGB/DPU coverage differs')
    seen=set()
    for pose in poses:
        meta=load(pose);i=meta['source_frame_id']
        if type(i)!=int or not 0<=i<count or i in seen:raise ValueError('Repeated/invalid camera keyframe')
        seen.add(i);row=tracking[i];store.read(meta)
        if meta['anchor_kind']!='slam_keyframe' or meta['timestamp_ns']!=int(row['timestamp_ns']) or meta['gray_crc']!=int(row['gray_crc']):
            raise ValueError('Camera keyframe/pose/RGB identity mismatch')
    gpu=result['gpu']
    for name in ('gpu','gpu_sparse'):
        value=gpu.get(name,{})
        if value.get('software',True) or value.get('vendor')!='ARM' or 'Mali' not in value.get('renderer','') or value.get('paints',0)<1:
            raise ValueError('Actual Mali camera display required')
    if gpu.get('last_frame')!=count-1 or gpu.get('dense_points',0)<1:raise ValueError('Final camera GPU delivery incomplete')
    proof=dict(format='KV260_MANUAL_LATEST_MAP_SOURCE_V1' if manual_latest else ('KV260_LIVE_CAMERA_SOURCE_V1' if stability_accepted else 'KV260_LIVE_CAMERA_DIAGNOSTIC_SOURCE_V1'),result_sha256=digest(control/'RESULT.json'),frames=count,
               first_valid_frame=first,last_source_frame=count-1,map_id=mid,continuity=continuity,
               validity=ratio,cpu_orb_calls=0,all_geometry_fps=count/elapsed,camera_sha256=digest(camera),
               raw_sequence_gaps=checked['raw_sequence_gaps'],original_result_status=result['status'],
               effective_acceptance_profile='stable_map_5fps',worker_sha256=digest(run/'dense/depth/worker.json'),
               stability_accepted=stability_accepted,diagnostic_only=not stability_accepted,
               failed_gates=accepted['failed_gates'],manual_control=manual)
    if manual_latest:proof.update(map_selection='Atlas current map at completed shutdown',single_map_required=False)
    return result,proof


def create(run,camera,output,diagnostic=False,manual_latest=False):
    run,camera,output=map(lambda p:Path(p).resolve(),(run,camera,output))
    if output.exists():raise ValueError('Fresh camera handoff directory required')
    result,proof=stable_camera_source(run,camera,diagnostic,manual_latest)
    return _package_verified_source(run,camera,output,result,proof,include_dense=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','camera','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--diagnostic',action='store_true',help='Explicit downstream localization experiment; no stability acceptance and no other gate relaxation')
    p.add_argument('--manual-latest',action='store_true',help='Operator-stopped run: hand off its final current map; retain multi-map and tracking warnings')
    r=create(**vars(p.parse_args()));print(json.dumps(dict(status=r['status'],map=r['map'],source=r['source'])))
