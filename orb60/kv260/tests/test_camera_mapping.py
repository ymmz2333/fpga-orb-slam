import csv
import json
from pathlib import Path
import pytest
from orb60.kv260.run_camera_mapping import verify_input
from orb60.kv260.camera_input import fourcc


def fixture(out):
    (out/'tracking').mkdir()
    profile=dict(width=1280,height=720,fourcc=fourcc('YUYV'),stride=2560,sizeimage=1280*720*2,
                 colorspace=8,ycbcr_encoding=1,quantization=0,transfer_function=1,
                 interval_numerator=1,interval_denominator=60,buffers=4,frames=2,sequence_gaps=3)
    sensor=[dict(source_frame_id=i,capture_sequence=seq,timestamp_ns=stamp,dequeued_ns=stamp+1000,sequence_gaps=gaps,gray_crc=42+i)
            for i,(seq,stamp,gaps) in enumerate(((10,100,0),(14,200,3)))]
    tracking=[dict(source_frame_id=i,timestamp_ns=100+i*100,gray_crc=42+i,cpu_orb_calls=0,engine_ns=10,count=12,pose_valid=0) for i in range(2)]
    def write(path,data):
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    write(out/'camera_frames.csv',sensor);write(out/'tracking/frames.csv',tracking)
    (out/'camera_profile.json').write_text(json.dumps(profile))
    (out/'camera_mapping_status.json').write_text(json.dumps(dict(status='INPUT_DRAINED_NO_MAP_INITIALIZED',mapping_verified=False)))
    (out/'network_mapping.json').write_text(json.dumps(dict(frames=2,valid_poses=0,cpu_orb_calls=0)))
    (out/'CAMERA_INPUT_COMPLETE').touch()
    return sensor,tracking,write


def test_no_map_is_only_input_component_and_raw_gaps_are_preserved(tmp_path):
    fixture(tmp_path);r=verify_input(tmp_path,2)
    assert r['raw_sequence_gaps']==3 and r['valid_poses']==0
    assert not r['map_status']['mapping_verified'] and r['first_valid_frame'] is None


@pytest.mark.parametrize('case',('gap','duplicate','backward','gray','cpu','missing_pl','partial','fake_complete','fake_mapping_verified'))
def test_camera_integrity_and_no_map_scope_cannot_be_weakened(tmp_path,case):
    sensor,tracking,write=fixture(tmp_path)
    if case=='gap':sensor[1]['sequence_gaps']=0
    if case=='duplicate':sensor[1]['capture_sequence']=10
    if case=='backward':sensor[1]['timestamp_ns']=90
    if case=='gray':tracking[1]['gray_crc']=0
    if case=='cpu':tracking[0]['cpu_orb_calls']=1
    if case=='missing_pl':tracking[0]['engine_ns']=0
    if case=='partial':tracking.pop()
    if case=='fake_complete':(tmp_path/'NATIVE_COMPLETE').touch()
    if case=='fake_mapping_verified':
        (tmp_path/'camera_mapping_status.json').write_text(json.dumps(dict(status='INPUT_DRAINED_NO_MAP_INITIALIZED',mapping_verified=True)))
    write(tmp_path/'camera_frames.csv',sensor);write(tmp_path/'tracking/frames.csv',tracking)
    with pytest.raises(ValueError):verify_input(tmp_path,2)
