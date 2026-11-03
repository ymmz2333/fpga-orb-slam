"""Exact PS voxel grouping with bounded uint64 keys; geometry stays unchanged."""
import numpy as np
from orb60.dense.geometry import VoxelMap as ReferenceVoxelMap


class PackedVoxelMap(ReferenceVoxelMap):
    @staticmethod
    def _group_keys(keys):
        if not len(keys):return np.empty(0,np.intp)
        low=keys.min(axis=0);high=keys.max(axis=0)
        # Python integer subtraction avoids signed int64 range overflow. Values
        # outside this lossless packing range use the original exact algorithm.
        if any(int(b)-int(a)>=(1<<21) for a,b in zip(low,high)):
            return ReferenceVoxelMap._group_keys(keys)
        local=(keys-low).astype(np.uint64)
        packed=(local[:,0]<<np.uint64(42))|(local[:,1]<<np.uint64(21))|local[:,2]
        # Numeric packed order is exactly the original signed xyz lexicographic
        # order, so even reduction order and floating point sums are preserved.
        return np.unique(packed,return_inverse=True)[1]
