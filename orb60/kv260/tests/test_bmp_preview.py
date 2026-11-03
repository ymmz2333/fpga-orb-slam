from types import SimpleNamespace
import zlib
import cv2
import numpy as np
import pytest
from orb60.kv260.preview_transport import validate_final_preview
from orb60.kv260.ps.build_bmp_preview import transform


def packet(image):
    ok,raw=cv2.imencode('.bmp',image);assert ok
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    return SimpleNamespace(jpeg=raw.tobytes(),meta=dict(image_codec='bmp',raw_gray_crc=zlib.crc32(gray.tobytes())))


def test_color_codec_and_original_gray_identity():
    image=np.random.default_rng(7015260).integers(0,256,(720,960,3),dtype=np.uint8)
    p=packet(image);validate_final_preview(p,'ram_bmp')
    decoded=cv2.imdecode(np.frombuffer(p.jpeg,np.uint8),cv2.IMREAD_COLOR)
    assert np.array_equal(image,decoded)
    p.meta['raw_gray_crc']^=1
    with pytest.raises(ValueError):validate_final_preview(p,'ram_bmp')


@pytest.mark.parametrize('what',['codec','magic','shape'])
def test_wrong_codec_or_shape_rejected(what):
    p=packet(np.zeros((720,960,3),np.uint8))
    if what=='codec':p.meta['image_codec']='jpeg'
    elif what=='magic':p.jpeg=b'not a bitmap'
    else:p=packet(np.zeros((360,480,3),np.uint8))
    with pytest.raises(ValueError):validate_final_preview(p,'ram_bmp')


HEADER=r'''void write(){
 cv::imencode(".jpg",f.image,jpeg,{cv::IMWRITE_JPEG_QUALITY,80}),"JPEG encode";
 s<<",\"source_gray\":";
}'''.replace('\\\\','\\')
MAIN='namespace {\nvoid helper(){}\n}\nvoid main(){new DenseFrameTelemetry(out+"/tracking/telemetry",false);}\n'


def test_generator_preserves_everything_except_codec_and_storage_hook():
    header,main=transform(HEADER,MAIN)
    assert '.bmp' in header and 'image_codec' in header
    assert 'kv_lossless_preview_folder' in main and 'ORB60_TELEMETRY_DIR' in main
    assert 'void helper(){}' in main


@pytest.mark.parametrize('header,main',[(HEADER+HEADER,MAIN),(HEADER,MAIN+MAIN),(HEADER.replace('.jpg','.png'),MAIN)])
def test_unreviewed_producer_source_fails_closed(header,main):
    with pytest.raises(ValueError):transform(header,main)
