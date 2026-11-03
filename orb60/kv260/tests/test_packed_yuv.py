import numpy as np
import pytest
from orb60.kv260.packed_yuv import unpack


def test_yuyv_and_uyvy_byte_orders_match_same_luma_and_color():
    a=np.empty((720,960,2),np.uint8);a[:,:,0]=16;a[:,:,1]=128
    a[:,1::2,0]=235
    lut=np.arange(256,dtype=np.uint8)
    bgr,gray=unpack(a,'YUYV',lut)
    bgr2,gray2=unpack(np.ascontiguousarray(a[:,:,::-1]),'UYVY',lut)
    assert np.array_equal(bgr,bgr2) and np.array_equal(gray,gray2)
    assert np.all(gray[:,::2]==16) and np.all(gray[:,1::2]==235)
    assert np.all(bgr[:,::2]==0) and np.all(bgr[:,1::2]==255)


def test_chroma_is_not_swapped_and_luma_lut_is_explicit():
    a=np.empty((720,960,2),np.uint8);a[:,:,0]=81;a[:,::2,1]=90;a[:,1::2,1]=240
    lut=np.arange(256,dtype=np.uint8);lut[81]=76
    bgr,gray=unpack(a,'YUYV',lut)
    assert bgr[:,:,2].min()>250 and bgr[:,:,:2].max()<3
    assert np.all(gray==76)


@pytest.mark.parametrize('kind,shape,lut',[('RGB',(720,960,2),np.arange(256,dtype=np.uint8)),('YUYV',(360,960,2),np.arange(256,dtype=np.uint8)),('UYVY',(720,960,2),np.arange(255,dtype=np.uint8))])
def test_packed_format_dimensions_and_lut_cannot_be_guessed(kind,shape,lut):
    with pytest.raises(ValueError):unpack(np.zeros(shape,np.uint8),kind,lut)
