from pathlib import Path
import json
import hashlib
import pytest
from orb60.kv260.ps.build_packed_bmp import color_cache_transform
from orb60.kv260.frame_store import FrameStore

SOURCE='''// retained prefix
void publish_rgb(const Frame& frame,const std::string& folder) {
 std::vector<uint8_t> png;
 cv::imencode(".png",frame.bgr,png,{cv::IMWRITE_PNG_COMPRESSION,1});
 auto path=folder+".png.part";check("RGB PNG encoding failed");
 write(png.data(),png.size());meta<<".png";
}
}
int main(){unchanged_geometry();}
'''


def test_cache_transform_rejects_unknown_encoders_and_preserves_geometry():
    changed=color_cache_transform(SOURCE)
    assert changed.endswith('int main(){unchanged_geometry();}\n')
    assert 'cv::imencode(".bmp",frame.bgr,bmp)' in changed
    assert '.png' not in changed
    with pytest.raises(ValueError):color_cache_transform(SOURCE+SOURCE)
    with pytest.raises(ValueError):color_cache_transform(SOURCE.replace('cv::IMWRITE_PNG_COMPRESSION,1','upstream_options'))


def test_existing_frame_store_reads_lossless_bmp_and_enforces_identity(tmp_path):
    import cv2
    import numpy as np
    store=FrameStore(tmp_path)
    image=np.arange(720*960*3,dtype=np.uint8).reshape(720,960,3)
    p=tmp_path/'f1.bmp';assert cv2.imwrite(str(p),image)
    meta=dict(source_frame_id=1,timestamp_ns=1000000001,gray_crc=123)
    record={**meta,'rgb':p.name,'rgb_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (tmp_path/'f1.json').write_text(json.dumps(record))
    assert np.array_equal(store.read(meta),image)
    with pytest.raises(ValueError):store.read({**meta,'gray_crc':124})
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):store.read(meta)
