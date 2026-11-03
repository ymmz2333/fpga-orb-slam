from orb60.kv260.map_continuity import audit

def frames(valid):return [dict(pose_valid=v) for v in valid]

def test_single_map_and_loss_segments():
    r=audit(frames([0,1,1,0,0,1,0]),'Creation of new map with id: 0\nCreation of new map with last KF id: 0')
    assert r['status']=='SINGLE_MAP_CREATION_PASS'
    assert r['tracking_loss_segments']==[dict(first_source_frame=3,last_source_frame=4,frames=2),dict(first_source_frame=6,last_source_frame=6,frames=1)]

def test_mid_video_reset_is_not_hidden_by_final_merge():
    r=audit(frames([0,1,0,1]),'Creation of new map with id: 0\nFPGA_ORB_NET frame=3 role=0\nCreation of new map with id: 1\nStored map with ID: 0')
    assert r['status']=='MAP_CONTINUITY_FAILED'
    assert r['maps_created']==[dict(map_id=0,last_completed_source_frame=None),dict(map_id=1,last_completed_source_frame=2)]

def test_repeated_map_zero_also_fails():
    assert audit(frames([1]),'Creation of new map with id: 0\nCreation of new map with id: 0')['status']=='MAP_CONTINUITY_FAILED'

def test_no_log_or_initialization_fails():
    assert audit(frames([1]),'')['status']=='MAP_CONTINUITY_FAILED'
    assert audit(frames([0,0]),'Creation of new map with id: 0')['status']=='MAP_CONTINUITY_FAILED'
