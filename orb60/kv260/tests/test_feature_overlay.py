import numpy as np
import cv2
import pytest
from orb60.kv260.feature_overlay import draw_batch


def test_each_feature_has_its_original_position_and_green_or_orange_marker():
    image=np.full((200,240,3),80,np.uint8)
    features=[[x+.25,y+.25,0,(x//30)%2] for y in range(20,190,30) for x in range(20,230,30)]
    original=np.array(features).copy();draw_batch(image,features)
    np.testing.assert_array_equal(features,original)
    for x,y,_,mapped in features:
        x,y=round(x),round(y);patch=image[y-5:y+6,x-5:x+6]
        assert np.count_nonzero(patch!=80)>8
        b,g,r=map(int,image[y,x+3])
        assert g>r and g>b if mapped else r>g>b
    assert np.all(image[:10]==80) and np.all(image[:,:10]==80)


def test_edge_clipping_and_empty_markers_do_not_touch_unrelated_pixels():
    image=np.full((40,40,3),80,np.uint8);draw_batch(image,[])
    assert np.all(image==80)
    draw_batch(image,[[0,0,0,1],[39,39,0,0],[-2,20,0,1]])
    assert np.all(image[10:30,10:30]==80)


def test_nonfinite_features_are_rejected():
    with pytest.raises(ValueError):draw_batch(np.zeros((20,20,3),np.uint8),[[float('nan'),1,0,1]])


@pytest.mark.parametrize('runs',(1,3,24))
def test_overlapping_colored_clipped_markers_match_original_circle_bytes(runs):
    rng=np.random.default_rng(718);source=rng.integers(0,256,size=(120,160,3),dtype=np.uint8)
    features=[[float(i%30)+.5,float(i%40)+.25,i%8,(i//(60//runs))%2] for i in range(60)]
    features.extend([[-1,0,0,0],[159,119,0,1]])
    actual=source.copy();expected=source.copy()
    for x,y,_,flag in features:cv2.circle(expected,(round(x),round(y)),3,(135,230,60) if flag else (40,188,245),1,cv2.LINE_AA)
    draw_batch(actual,features)
    assert actual.tobytes()==expected.tobytes()
