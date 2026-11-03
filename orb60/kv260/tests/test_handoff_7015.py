"""7015 handoff rejects partial, fragmented and changed mapping evidence."""
import csv
import json
import hashlib
import pytest
from orb60.kv260.handoff_7015 import stable_source


def fixture(tmp_path):
    run=tmp_path/'run';control=tmp_path/'run_control'
    (run/'tracking/map').mkdir(parents=True);control.mkdir()
    frames=[dict(source_frame_id=i,pose_valid=int(i>0),cpu_orb_calls=0) for i in range(4)]
    with (run/'tracking/frames.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(frames[0]));writer.writeheader();writer.writerows(frames)
    (run/'NATIVE_COMPLETE').write_text('test fixture only')
    (run/'tracking/map/EXPORT_COMPLETE').write_text('test fixture only')
    (run/'tracking/map/map_id.txt').write_text('0\n')
    (control/'native.log').write_text('Creation of new map with id: 0\n')
    result=dict(status='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS',frontend='actual_zynq7015_PL',
                mapping=dict(mapping='KV260_PS',frontend='actual_zynq7015_PL',cpu_orb_calls=0),frames_requested=4,source_frames_total=4,acceptance_profile='stable_map_handoff',
                profiling=False,kernel_tainted=0,timings=dict(all_geometry_fps=2),
                frame_checks=dict(frames=4,valid_after_initialization=1.,source_identity_mismatches=0,
                                  physical_feature_mismatches=0,cpu_orb_calls=0),
                dense=dict(status='COMPLETED',hardware_inference_verified=True))
    (control/'RESULT.json').write_text(json.dumps(result))
    return run,control,result


def test_recomputes_continuity_and_does_not_require_obsolete_fps_goal(tmp_path):
    run,control,result=fixture(tmp_path)
    accepted,proof=stable_source(run)
    assert proof['map_id']==0 and proof['frames']==4 and proof['validity']==1.
    assert accepted['timings']['all_geometry_fps']==2


@pytest.mark.parametrize('kind',('failed','partial','prefix','fragmented','wrong_export','cpu_orb','changed_validity','no_final_export','no_actual_dpu'))
def test_rejects_changed_or_unaccepted_sources(tmp_path,kind):
    run,control,result=fixture(tmp_path)
    if kind=='failed':result['status']='FAILED_TARGET_GATES'
    elif kind=='partial':result['frames_requested']=5
    elif kind=='prefix':result['source_frames_total']=5
    elif kind=='fragmented':
        (control/'native.log').write_text('Creation of new map with id: 0\nCreation of new map with id: 1\n')
    elif kind=='wrong_export':(run/'tracking/map/map_id.txt').write_text('1\n')
    elif kind=='cpu_orb':
        p=run/'tracking/frames.csv';s=p.read_text();s=s.replace('2,1,0','2,1,1');p.write_text(s)
    elif kind=='changed_validity':result['frame_checks']['valid_after_initialization']=.99
    elif kind=='no_final_export':(run/'tracking/map/EXPORT_COMPLETE').unlink()
    elif kind=='no_actual_dpu':result['dense']['hardware_inference_verified']=False
    (control/'RESULT.json').write_text(json.dumps(result))
    with pytest.raises(ValueError):stable_source(run)


def test_explicit_user_review_is_bound_to_exact_result_and_tail(tmp_path):
    run,control,result=fixture(tmp_path)
    frames=[dict(source_frame_id=i,pose_valid=int(140<=i<2213),cpu_orb_calls=0) for i in range(2297)]
    with (run/'tracking/frames.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(frames[0]));writer.writeheader();writer.writerows(frames)
    result.update(status='FAILED_TARGET_GATES',frames_requested=2297,source_frames_total=2297,
                  acceptance_profile='stable_map_5fps',timings=dict(all_geometry_fps=13.385))
    result['frame_checks'].update(frames=2297,valid_after_initialization=2073/2157)
    p=control/'RESULT.json';p.write_text(json.dumps(result))
    review=dict(format='KV260_USER_MAPPING_REVIEW_V1',decision='ACCEPT_CURRENT_MAP_WITH_INVALID_TAIL',
                result_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),frames=2297,first_valid_frame=140,
                valid_poses=2073,acceptance_profile='stable_map_5fps_tail84',
                approved_loss_segments=[dict(first_source_frame=2213,last_source_frame=2296,frames=84)])
    receipt=control/'review.json';receipt.write_text(json.dumps(review))
    with pytest.raises(ValueError):stable_source(run)
    _,proof=stable_source(run,receipt)
    assert proof['original_result_status']=='FAILED_TARGET_GATES'
    assert json.loads(p.read_text())['status']=='FAILED_TARGET_GATES'
    # Another result cannot borrow the approval even when the map ID is equal.
    p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='review does not match'):stable_source(run,receipt)
