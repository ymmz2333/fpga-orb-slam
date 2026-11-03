import numpy as np
import pytest
from orb60.kv260.camera_input import fourcc,validate_pair,validate_profile,to_bgr,validate_calibration
from orb60.demo_bridge.calibration import encode,cropped,generate


def profile(name='YUYV'):
    return dict(width=1280,height=720,fourcc=fourcc(name),stride=2560,sizeimage=1280*720*2,
                colorspace=8,ycbcr_encoding=0,quantization=0,transfer_function=1,
                interval_numerator=1,interval_denominator=60,buffers=4)


@pytest.mark.parametrize('name',('YUYV','UYVY'))
def test_color_luma_order_and_limited_range(name):
    p=profile(name);validate_profile(p)
    # Limited-range black, white and red. Independent BT.601 reference values.
    packed=np.zeros((720,960,2),np.uint8)
    pairs=np.array([[16,128,16,128],[235,128,235,128],[81,90,81,240]],np.uint8)
    for i,pair in enumerate(pairs):
        if name=='UYVY':pair=pair[[1,0,3,2]]
        packed[:,i*2:(i+1)*2]=pair.reshape(1,2,2)
    offset=int(name=='UYVY');gray=packed[:,:,offset].copy();validate_pair(packed,gray,p)
    bgr=to_bgr(packed,p)
    assert np.max(bgr[0,0])==0 and np.min(bgr[0,2])==255
    assert np.max(np.abs(bgr[0,4].astype(int)-[0,0,255]))<=1
    gray[0,0]^=1
    with pytest.raises(ValueError,match='same frame'):validate_pair(packed,gray,p)


@pytest.mark.parametrize('field,value',(('fourcc',1196444237),('width',960),('stride',2559),('sizeimage',1),
    ('buffers',100),('colorspace',3),('ycbcr_encoding',2),('quantization',1),('interval_numerator',0)))
def test_wrong_format_geometry_colorimetry_rejected(field,value):
    p=profile();p[field]=value
    with pytest.raises(ValueError):validate_profile(p)


def test_new_calibration_is_explicit_crop(tmp_path):
    c=dict(width=1280,height=720,fx=757.1979,fy=757.9716,cx=659.6236,cy=352.7898,
           d0=.088847,d1=-.12031,d2=-.00082,d3=-.00352,d4=.054812)
    source,working=tmp_path/'source.csv',tmp_path/'working.csv'
    source.write_bytes(encode(c));working.write_bytes(encode(cropped(c)))
    assert validate_calibration(source,working)['cx']==c['cx']-160
    generate(source,tmp_path/'usb3',fps=60)
    assert 'Camera.fps: 60.0' in (tmp_path/'usb3/camera_rk.yaml').read_text()
    generate(source,tmp_path/'legacy')
    assert 'Camera.fps: 30.0' in (tmp_path/'legacy/camera_rk.yaml').read_text()
    with pytest.raises(ValueError):generate(source,tmp_path/'invalid',fps=float('nan'))
    bad=cropped(c);bad['cx']=480;working.write_bytes(encode(bad))
    with pytest.raises(ValueError,match='calibration'):validate_calibration(source,working)


def test_nonpacked_or_wrong_dtype_rejected():
    with pytest.raises(ValueError):fourcc('MJPG')
    with pytest.raises(ValueError):to_bgr(np.zeros((720,960,3),np.uint8),profile())
    with pytest.raises(ValueError):validate_pair(np.zeros((720,960,2)),np.zeros((720,960),np.uint8),profile())
