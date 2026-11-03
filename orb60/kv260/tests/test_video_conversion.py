import av
import numpy as np
from orb60.kv260.video_conversion import BgrConverter


def test_persistent_converter_matches_original_for_varying_content_and_formats():
    converter=BgrConverter(True);rng=np.random.default_rng(260)
    for width,height,fmt in ((96,72,'yuv420p'),(96,72,'yuv420p'),(64,48,'yuv444p'),(96,72,'yuv420p'),(96,72,'bgr24')):
        raw=rng.integers(0,256,(height,width,3),dtype=np.uint8)
        frame=av.VideoFrame.from_ndarray(raw,format='bgr24').reformat(format=fmt)
        expected=frame.to_ndarray(format='bgr24')
        assert np.array_equal(converter.convert(frame),expected)
