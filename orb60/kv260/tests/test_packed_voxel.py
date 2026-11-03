"""Exact agreement with the independent existing xyz sort and voxel reductions."""
import numpy as np
import pytest
from orb60.kv260.voxel import PackedVoxelMap,ReferenceVoxelMap


@pytest.mark.parametrize('offset',(-2**63,-10000000,0,2**63-10000000))
def test_group_ids_match_signed_xyz_sort_near_int64_boundaries(offset):
    rng=np.random.default_rng(829)
    keys=rng.integers(0,500000,size=(10000,3),dtype=np.int64)+np.int64(offset)
    keys[5000:]=keys[:5000]
    np.testing.assert_array_equal(PackedVoxelMap._group_keys(keys),np.unique(keys,axis=0,return_inverse=True)[1])


def test_wide_keys_use_exact_reference_without_collision_or_overflow():
    keys=np.array([[-2**63,0,0],[2**63-1,0,0],[0,2**21,0],[0,0,2**21],[0,0,0],[-2**63,0,0]],np.int64)
    np.testing.assert_array_equal(PackedVoxelMap._group_keys(keys),np.unique(keys,axis=0,return_inverse=True)[1])


def test_repeated_weighted_fusion_and_capacity_rebin_are_byte_identical():
    rng=np.random.default_rng(619);reference=ReferenceVoxelMap(.01,150);candidate=PackedVoxelMap(.01,150)
    for _ in range(4):
        xyz=rng.normal(size=(6000,3));rgb=rng.integers(0,256,size=(6000,3),dtype=np.uint8)
        for voxel in (reference,candidate):voxel.add(xyz,rgb)
        assert candidate.edge==reference.edge and candidate.resolutions==reference.resolutions
        assert candidate.sums.tobytes()==reference.sums.tobytes()
        assert candidate.counts.tobytes()==reference.counts.tobytes()
        assert all(a.tobytes()==b.tobytes() for a,b in zip(candidate.arrays(),reference.arrays()))
