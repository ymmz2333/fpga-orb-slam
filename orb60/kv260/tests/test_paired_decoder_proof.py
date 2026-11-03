import json
import pytest
from orb60.kv260 import paired_frame_decoder as decoder


@pytest.mark.parametrize('indices',[[True],[1,1],[2,1],[-1],[2297],list(range(65)),[0,2,4,6,8]])
def test_repair_set_cannot_expand_silently(indices):
    with pytest.raises(ValueError):decoder.validate_indices(indices,2297)


def test_empty_or_bounded_contiguous_repair_is_supported():
    decoder.validate_indices([],2297);decoder.validate_indices(list(range(974,990)),2297)
    with pytest.raises(ValueError):decoder.validate_indices([1,2,3],20)


def test_pixel_proof_binds_both_channels_source_and_complete_repair(tmp_path,monkeypatch):
    context=dict(video_sha256='video',identities_sha256='gray',color_identities_sha256='rgb',
                 source_proof_sha256='source',decoder_source_sha256='code',pyav='test',frames=2297)
    monkeypatch.setattr(decoder,'context',lambda *args:context)
    plan=tmp_path/'plan.json';plan.write_text(json.dumps(dict(indices=[974])))
    proof=tmp_path/'proof.json'
    good=dict(status='EXACT_PAIRED_FRAME_REPAIR_PIXEL_PASS',**context,plan_sha256=decoder.digest(plan),compared_frames=2297,
              gray_pixel_mismatches=0,bgr_pixel_mismatches=0,decoder=dict(status='EXACT_PAIRED_FRAME_REPAIR_DRAINED',repaired=[974]))
    proof.write_text(json.dumps(good));decoder.validate_proof(proof,None,None,None,None,plan)
    for key,value in [('decoder_source_sha256','different'),('color_identities_sha256','different'),
                      ('compared_frames',2296),('gray_pixel_mismatches',1),('bgr_pixel_mismatches',1),
                      ('decoder',dict(status='EXACT_PAIRED_FRAME_REPAIR_DRAINED',repaired=[]))]:
        proof.write_text(json.dumps({**good,key:value}))
        with pytest.raises(ValueError):decoder.validate_proof(proof,None,None,None,None,plan)
