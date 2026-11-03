"""Source-gate fixtures are artificial; these tests never assert board success."""
import json
from pathlib import Path
import numpy as np
import pytest
from orb60.kv260.tests.test_camera_mapping import fixture as input_fixture
from orb60.kv260.run_camera_mapping import verify_input
from orb60.kv260.run_network_system import digest
from orb60.kv260.frame_store import FrameStore
from orb60.kv260.handoff_camera_7015 import stable_camera_source


def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))


def fixture(tmp_path):
    run=tmp_path/'run';run.mkdir();sensor,tracking,write=input_fixture(run)
    control=tmp_path/'run_control';control.mkdir()
    camera=tmp_path/'camera.csv';camera.write_bytes((Path(__file__).parents[1]/'config/camera_usb_20261103/camera_orb.csv').read_bytes())
    store=FrameStore(run/'dense/rgb_cache')
    meta=store.publish(1,200,np.zeros((720,960,3),np.uint8),np.zeros((720,960),np.uint8))
    sensor[1]['gray_crc']=tracking[1]['gray_crc']=meta['gray_crc'];tracking[1]['pose_valid']=1
    write(run/'camera_frames.csv',sensor);write(run/'tracking/frames.csv',tracking)
    put(run/'camera_mapping_status.json',dict(status='CAMERA_MAP_EXPORTED_VALIDATION_PENDING',mapping_verified=False))
    put(run/'network_mapping.json',dict(frames=2,valid_poses=1,cpu_orb_calls=0,selected_keyframes=1,
        started_monotonic_ns=1_000_000,source_input='actual_KV260_V4L2_camera',gray_input='camera_original_Y'))
    (run/'NATIVE_COMPLETE').touch();(run/'tracking/map').mkdir()
    (run/'tracking/map/EXPORT_COMPLETE').touch();(run/'tracking/map/map_id.txt').write_text('0\n')
    (control/'native.log').write_text('Creation of new map with id: 0\n')
    put(run/'dense/depth/worker.json',dict(backend='dpu',hardware_inference_verified=True,hardware_driver='vivado',
        model_sha256='a'*64,frames=[dict(reused=False)]))
    meta.update(anchor_kind='slam_keyframe');put(run/'dense/color_poses/f1.json',meta)
    put(run/'dense/blocks/final_pose_update.json',dict(map_id=0,accepted=['block0']))
    put(run/'dense/blocks/block0.final.json',dict(map_id=0,geometry_backend='actual_kv260_pl_point_project'))
    gpu=dict(software=False,vendor='ARM',renderer='Mali fixture only',paints=1)
    state=dict(status='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS',input='actual_KV260_USB3_camera',frontend='actual7015_PL',
        mapping='KV260_PS',mapping_verified=True,hardware_inference_verified=True,gpu_hardware_verified=True,
        camera_sha256=digest(camera),model_sha256='a'*64,frames_requested=2,camera_input=verify_input(run,2),kernel_tainted=0,
        dense=dict(status='COMPLETED',hardware_inference_verified=True,hardware_projection_verified=True,
                   completed_monotonic_ns=101_000_000,maps=[dict(map_id=0,points=2)],timings=[{}]),
        gpu=dict(gpu=gpu,gpu_sparse=gpu,last_frame=1,dense_points=2))
    put(control/'RESULT.json',state)
    return run,control,camera,state


def test_camera_gate_recomputes_frame_map_backend_and_speed(tmp_path):
    run,control,camera,state=fixture(tmp_path)
    _,proof=stable_camera_source(run,camera)
    assert proof['format']=='KV260_LIVE_CAMERA_SOURCE_V1' and proof['all_geometry_fps']==20
    assert proof['raw_sequence_gaps']==3 and proof['map_id']==0


@pytest.mark.parametrize('case',('stationary','saved_video','wrong_camera','changed_frames','cpu_orb','fragmented',
    'wrong_map','slow','nan_time','no_dpu','reused_depth','wrong_model','wrong_color','cpu_projection','software_gpu'))
def test_camera_handoff_rejects_missing_or_changed_actual_evidence(tmp_path,case):
    run,control,camera,state=fixture(tmp_path)
    if case=='stationary':state['status']='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED'
    elif case=='saved_video':state['input']='saved_video'
    elif case=='wrong_camera':camera.write_bytes(b'wrong camera')
    elif case=='changed_frames':state['camera_input']['frames']=3
    elif case=='cpu_orb':
        p=run/'tracking/frames.csv';p.write_text(p.read_text().replace(',0,10,12,',',1,10,12,'))
    elif case=='fragmented':(control/'native.log').write_text('Creation of new map with id: 0\nCreation of new map with id: 1\n')
    elif case=='wrong_map':(run/'tracking/map/map_id.txt').write_text('1\n')
    elif case=='slow':state['dense']['completed_monotonic_ns']=1_001_000_000
    elif case=='nan_time':state['dense']['completed_monotonic_ns']=float('nan')
    elif case=='no_dpu':state['dense']['hardware_inference_verified']=False
    elif case in ('reused_depth','wrong_model'):
        p=run/'dense/depth/worker.json';r=json.loads(p.read_text())
        if case=='reused_depth':r['frames'][0]['reused']=True
        else:r['model_sha256']='b'*64
        put(p,r)
    elif case=='wrong_color':(run/'dense/rgb_cache/f1.png').write_bytes(b'corrupt')
    elif case=='cpu_projection':put(run/'dense/blocks/block0.final.json',dict(map_id=0,geometry_backend='cpu'))
    elif case=='software_gpu':state['gpu']['gpu']['software']=True
    put(control/'RESULT.json',state)
    with pytest.raises(ValueError):stable_camera_source(run,camera)


def diagnostic_fixture(tmp_path):
    run,control,camera,state=fixture(tmp_path)
    import csv
    def read(p):
        with p.open(newline='') as f:return list(csv.DictReader(f))
    def write(p,data):
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    sensor=read(run/'camera_frames.csv');tracking=read(run/'tracking/frames.csv')
    tracking[0]['pose_valid']='1'
    for i in (2,3):
        sensor.append(dict(sensor[-1],source_frame_id=i,capture_sequence=13+i,
                           timestamp_ns=(i+1)*100,dequeued_ns=(i+1)*100+1000))
        tracking.append(dict(tracking[-1],source_frame_id=i,timestamp_ns=(i+1)*100,pose_valid=int(i==3)))
    write(run/'camera_frames.csv',sensor);write(run/'tracking/frames.csv',tracking)
    profile=json.loads((run/'camera_profile.json').read_text());profile['frames']=4
    put(run/'camera_profile.json',profile)
    native=state['camera_input']['native'];native.update(frames=4,valid_poses=3)
    put(run/'network_mapping.json',native)
    state.update(status='FAILED_TARGET_GATES',mapping_verified=False,frames_requested=4,
                 camera_input=verify_input(run,4),failed_gates=['Tracking stability below98% after initialization'])
    state['gpu']['last_frame']=3;put(control/'RESULT.json',state)
    return run,control,camera,state


def test_diagnostic_handoff_is_explicit_and_preserves_failed_result(tmp_path):
    run,control,camera,state=diagnostic_fixture(tmp_path)
    before=(control/'RESULT.json').read_bytes()
    with pytest.raises(ValueError):stable_camera_source(run,camera)
    _,proof=stable_camera_source(run,camera,diagnostic=True)
    assert proof['format']=='KV260_LIVE_CAMERA_DIAGNOSTIC_SOURCE_V1'
    assert proof['diagnostic_only'] and not proof['stability_accepted']
    assert proof['validity']==.75 and proof['original_result_status']=='FAILED_TARGET_GATES'
    assert proof['failed_gates']==state['failed_gates']
    assert (control/'RESULT.json').read_bytes()==before


@pytest.mark.parametrize('case',('slow','fragmented','no_dpu','software_gpu','additional_failure','fake_verified'))
def test_diagnostic_handoff_cannot_bypass_other_gates(tmp_path,case):
    run,control,camera,state=diagnostic_fixture(tmp_path)
    if case=='slow':state['dense']['completed_monotonic_ns']=2_001_000_000
    if case=='fragmented':(control/'native.log').write_text('Creation of new map with id: 0\nCreation of new map with id: 1\n')
    if case=='no_dpu':state['hardware_inference_verified']=False
    if case=='software_gpu':state['gpu']['gpu']['software']=True
    if case=='additional_failure':state['failed_gates'].append('Another failure')
    if case=='fake_verified':state['mapping_verified']=True
    put(control/'RESULT.json',state)
    with pytest.raises(ValueError):stable_camera_source(run,camera,diagnostic=True)


def latest_fixture(tmp_path):
    run,control,camera,state=diagnostic_fixture(tmp_path)
    state.update(manual_control=True,manual_stop=dict(status='OPERATOR_STOP_DRAINED',frames=4))
    put(run/'manual_stop.json',state['manual_stop'])
    (control/'native.log').write_text('Creation of new map with id: 0\nCreation of new map with id: 1\n')
    state['failed_gates'].append('Whole-video SLAM created multiple maps or its map creation record is missing')
    (run/'tracking/map/map_id.txt').write_text('1\n')
    state['dense']['maps']=[dict(map_id=0,points=3),dict(map_id=1,points=2)]
    put(run/'dense/blocks/final_pose_update.json',dict(map_id=1,accepted=['block0']))
    put(run/'dense/blocks/block0.final.json',dict(map_id=1,geometry_backend='actual_kv260_pl_point_project'))
    put(control/'RESULT.json',state)
    return run,control,camera,state


def test_manual_latest_selects_current_map_without_relabeling_multimap_failure(tmp_path):
    run,control,camera,state=latest_fixture(tmp_path);before=(control/'RESULT.json').read_bytes()
    with pytest.raises(ValueError):stable_camera_source(run,camera,diagnostic=True)
    _,proof=stable_camera_source(run,camera,manual_latest=True)
    assert proof['map_id']==1 and proof['single_map_required'] is False
    assert proof['format']=='KV260_MANUAL_LATEST_MAP_SOURCE_V1'
    assert not proof['stability_accepted'] and proof['failed_gates']==state['failed_gates']
    assert (control/'RESULT.json').read_bytes()==before


@pytest.mark.parametrize('case',('not_manual','bad_stop','unrecorded_map','missing_cloud','wrong_cloud','slow','wrong_camera','no_dpu'))
def test_latest_selection_keeps_stop_identity_geometry_and_hardware_checks(tmp_path,case):
    run,control,camera,state=latest_fixture(tmp_path)
    if case=='not_manual':state['manual_control']=False
    if case=='bad_stop':put(run/'manual_stop.json',dict(status='OPERATOR_STOP_DRAINED',frames=3))
    if case=='unrecorded_map':(run/'tracking/map/map_id.txt').write_text('99\n')
    if case=='missing_cloud':state['dense']['maps']=[dict(map_id=0,points=3)]
    if case=='wrong_cloud':put(run/'dense/blocks/final_pose_update.json',dict(map_id=0,accepted=['block0']))
    if case=='slow':state['dense']['completed_monotonic_ns']=2_001_000_000
    if case=='wrong_camera':camera.write_bytes(b'wrong')
    if case=='no_dpu':state['hardware_inference_verified']=False
    put(control/'RESULT.json',state)
    with pytest.raises(ValueError):stable_camera_source(run,camera,manual_latest=True)
