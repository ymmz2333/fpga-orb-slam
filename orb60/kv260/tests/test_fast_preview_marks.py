import numpy as np
import pytest
from orb60.kv260.feature_overlay import draw_fast


def test_fast_marks_preserve_inputs_and_last_marker_color():
    image=np.zeros((16,16,3),np.uint8);features=np.array([[8.,8.,0.,1.],[8.,8.,0.,0.]])
    before=features.copy();draw_fast(image,features)
    assert np.array_equal(features,before)
    assert np.array_equal(image[8,11],[40,188,245])
    assert np.array_equal(image[8,8],[0,0,0])


def test_clipping_empty_and_single_feature_keep_valid_pixels():
    a=np.zeros((8,8,3),np.uint8);draw_fast(a,[]);assert not a.any()
    draw_fast(a,[[0.,0.,0.,1.]])
    assert np.array_equal(a[0,3],[135,230,60])
    assert not a[7,7].any()
    with pytest.raises(ValueError):draw_fast(a,[[np.nan,0,0,1]])
