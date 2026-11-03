import json
import pytest
from orb60.kv260.frame_decoder import prepare_plan,validate_proof


def diagnostic(indices=(974,),frames=2297):
    return dict(status='FAILED_SOURCE_PIXELS',thread_type='FRAME',threads=5,frames=frames,
                pixel_mismatches=[dict(source_frame_id=i) for i in indices],video_sha256='a'*64,identities_sha256='b'*64)


def test_failed_decoder_evidence_stays_failed_and_plan_is_not_acceptance(tmp_path):
    p=tmp_path/'failed.json';p.write_text(json.dumps(diagnostic()));before=p.read_bytes()
    result=prepare_plan(p,tmp_path/'plan.json','14.2.0')
    assert result['status']=='REPAIR_PLAN_UNVERIFIED' and result['indices']==[974]
    assert p.read_bytes()==before


@pytest.mark.parametrize('indices,frames',(((),2297),((974,974),2297),((-1,),2297),((2297,),2297),(tuple(range(65)),2297),((1,3,5,7,9),2297),((1,2),20)))
def test_unbounded_duplicate_or_invalid_repair_windows_are_rejected(tmp_path,indices,frames):
    p=tmp_path/'failed.json';p.write_text(json.dumps(diagnostic(indices,frames)))
    with pytest.raises(ValueError):prepare_plan(p,tmp_path/'plan.json','14.2.0')


def test_unverified_plan_is_not_a_production_acceptance_proof(tmp_path):
    p=tmp_path/'proof.json';p.write_text(json.dumps({'status':'REPAIR_PLAN_UNVERIFIED'}))
    a=tmp_path/'video';a.write_bytes(b'video');b=tmp_path/'identities';b.write_bytes(b'csv');c=tmp_path/'plan';c.write_bytes(b'{}')
    with pytest.raises(ValueError):validate_proof(p,a,b,c)
