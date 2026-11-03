import json
import pytest
from orb60.kv260.tracking_trace import check,summarize,validate_config,BUILD_STATUS
from orb60.kv260.ps.build_tracking_trace import transform


def test_trace_can_never_be_accepted_as_nonprofile_performance():
    assert not validate_config({},'NATIVE_PACKED_BMP_COMPONENT_PASS')
    assert validate_config({'tracking_trace':True,'profile':True},BUILD_STATUS)
    for cfg,status in [({'tracking_trace':True},BUILD_STATUS),({},BUILD_STATUS),({'tracking_trace':True,'profile':True},'NATIVE_PACKED_BMP_COMPONENT_PASS'),({'tracking_trace':1,'profile':True},BUILD_STATUS)]:
        with pytest.raises(ValueError):validate_config(cfg,status)


def fixture(tmp_path):
    row=dict(source_frame_id=0,timestamp_ns=12345,features=1,tracking_state=2,events_dropped=0,levels=[1]+[0]*7,angle_bins=[1]+[0]*31,tcw=[0.]*12,events=[{'stage':'tracking_enter'},{'stage':'tracking_exit'}])
    actual=[dict(source_frame_id='0',timestamp_ns='12345',count='1',tracking_state='2',pose_valid='1')]
    path=tmp_path/'tracking_diagnostics.part000000.jsonl'
    return row,actual,path


def test_trace_pairs_every_source_and_records_branch_counts(tmp_path):
    row,a,p=fixture(tmp_path);p.write_text(json.dumps(row)+'\n')
    r=check(tmp_path,a)
    assert r['frames']==1 and r['stage_counts']['tracking_exit']==1
    assert r['invalid_frames']==[]


@pytest.mark.parametrize('field,value',[('timestamp_ns',12346),('features',2),('events_dropped',1),('levels',[0]*8),('tcw',None),('events',[{'stage':'tracking_enter'}])])
def test_corrupted_or_incomplete_diagnostic_is_rejected(tmp_path,field,value):
    row,a,p=fixture(tmp_path);row[field]=value;p.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError):check(tmp_path,a)


def test_missing_and_extra_frames_rejected(tmp_path):
    row,a,p=fixture(tmp_path)
    with pytest.raises(ValueError):check(tmp_path,a)
    p.write_text(json.dumps(row)+'\n'+json.dumps(row)+'\n')
    with pytest.raises(ValueError):check(tmp_path,a)


def test_summary_distinguishes_initialization_from_later_loss(tmp_path):
    import csv
    row,a,p=fixture(tmp_path);data=[];journal=[]
    for i,ok in enumerate([False,True,True,False,False,True]):
        r=dict(row,source_frame_id=i,timestamp_ns=12345+i,tracking_state=2 if ok else 3,tcw=row['tcw'] if ok else None)
        if i>=3:r['events']=row['events']+[dict(stage='motion_result',accepted=0),dict(stage='relocalization_candidates',count=0)]
        data.append(r);journal.append(dict(a[0],source_frame_id=str(i),timestamp_ns=str(12345+i),tracking_state=str(r['tracking_state']),pose_valid=str(int(ok))))
    p.write_text(''.join(json.dumps(r)+'\n' for r in data));csv_path=tmp_path/'frames.csv'
    with csv_path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(journal[0]));writer.writeheader();writer.writerows(journal)
    result=summarize(tmp_path,csv_path,tmp_path/'summary.json')
    assert result['post_initialization_invalid_segments']==[dict(first=3,last=4,frames=2)]
    assert result['rejected_branch_counts']=={'motion_result':2}
    assert result['relocalization_candidate_count_range']==[0,0]


def test_transform_keeps_original_math_and_only_adds_observation():
    h='#include <cstdint>\n    r.records_crc=orb_crc32(payload.data()+128,count*64);\n'
    e='''    FeatureIO::Configure("fpga-pipeline",argv[5]);
            const int state=slam.GetTrackingState();const bool ok=state==2&&pose.matrix().allFinite();valid+=ok;
    journal.close();source.close();'''
    hh,ee=transform(h,e)
    assert 'BridgeDiag::begin(trace_frame++,stamp,count,payload.data()+128)' in hh
    assert 'tracking_trace->write(state,ok?tcw:nullptr)' in ee
    with pytest.raises(ValueError):transform(h.replace('count*64','0'),e)
