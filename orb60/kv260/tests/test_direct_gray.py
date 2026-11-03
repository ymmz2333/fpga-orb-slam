import csv
import struct
import zlib
import numpy as np
import pytest
from orb60.kv260.direct_gray import pair_header,validate_headers
from orb60.kv260.source_frame_map import FrozenFrameIdentities


def test_packet_keeps_independent_gray_and_rgb_integer_identity():
    bgr=np.full((720,960,3),27,np.uint8);gray=np.full((720,960),31,np.uint8)
    stamp=1793620000123456789
    packet=pair_header(17,stamp,bgr,gray)
    assert struct.unpack('<8sQQII',packet)==(b'ORBPAIR1',17,stamp,zlib.crc32(bgr.tobytes()),zlib.crc32(gray.tobytes()))


@pytest.mark.parametrize('index,stamp',[(True,1),(0,1.0),(-1,1),(8192,1),(0,0),(0,2**64)])
def test_invalid_pair_identity_is_rejected(index,stamp):
    with pytest.raises(ValueError):pair_header(index,stamp,np.zeros((720,960,3),np.uint8),np.zeros((720,960),np.uint8))


def test_rgb_and_gray_must_be_contiguous_original_dimensions():
    bgr=np.zeros((720,960,3),np.uint8);gray=np.zeros((720,960),np.uint8)
    for a,b in [(bgr[:,::-1],gray),(bgr,gray.astype(np.float32)),(bgr[:100],gray)]:
        with pytest.raises(ValueError):pair_header(0,1,a,b)


def test_preview_checks_both_independent_source_channels(tmp_path):
    gray=tmp_path/'gray.csv';rgb=tmp_path/'rgb.csv'
    gray.write_text('source_frame_id,timestamp_ns,gray_crc\n0,1793620000123456789,123\n')
    rgb.write_text('source_frame_id,timestamp_ns,bgr_crc\n0,1793620000123456789,456\n')
    proof=FrozenFrameIdentities(gray,rgb)
    meta=dict(frame_index=0,timestamp_ns=1793620000123456789,raw_gray_crc=123,source_bgr_crc=456)
    proof.check(meta)
    for bad in ({**meta,'source_bgr_crc':457},{**meta,'raw_gray_crc':124},{**meta,'frame_index':1}):
        with pytest.raises(ValueError):proof.check(bad)
    del meta['source_bgr_crc']
    with pytest.raises(ValueError):proof.check(meta)
    rgb.write_text('source_frame_id,timestamp_ns,bgr_crc\n0,1793620000123456790,456\n')
    with pytest.raises(ValueError):FrozenFrameIdentities(gray,rgb)


def test_native_manifest_headers_reject_crlf_before_launch(tmp_path):
    gray=tmp_path/'gray.csv';rgb=tmp_path/'rgb.csv'
    gray.write_bytes(b'source_frame_id,timestamp_ns,gray_crc\n');rgb.write_bytes(b'source_frame_id,timestamp_ns,bgr_crc\n')
    validate_headers(gray,rgb)
    gray.write_bytes(b'source_frame_id,timestamp_ns,gray_crc\r\n')
    with pytest.raises(ValueError):validate_headers(gray,rgb)
