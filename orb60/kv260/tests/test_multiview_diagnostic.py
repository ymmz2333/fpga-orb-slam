"""Independent exact-Hamming diagnosis has a landmark-level ratio test."""
import numpy as np
from orb60.kv260.analyze_localization_diagnostic import distinct_matches


def test_multiple_views_of_one_point_do_not_compete_in_ratio():
    views=np.array([[255]*32,[255]*32,[170]*32],np.uint8);views[1,0]^=3
    query=np.full((1,32),255,np.uint8);query[0,0]^=1
    # Both first views differ by exactly one bit, but are the same point.
    assert distinct_matches(query,views,[10,10,20])==[(0,10,1)]
    # The identical two observations belonging to different points are ambiguous.
    assert distinct_matches(query,views,[10,11,20])==[]


def test_query_features_cannot_claim_the_same_landmark_twice():
    train=np.array([[255]*32,[170]*32],np.uint8)
    query=np.full((2,32),255,np.uint8);query[1,0]^=1
    assert distinct_matches(query,train,[10,20])==[(0,10,0)]
