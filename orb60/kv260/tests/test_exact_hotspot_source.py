import pytest
from orb60.kv260.ps.build_exact_hotspots import extract_grid


SOURCE='''// license
#include "Frame.h"
namespace ORB_SLAM3 {
vector<size_t> Frame::GetFeaturesInArea(const float& x) const {
 vector<size_t> vIndices;
 vIndices.reserve(N);
 const vector<size_t> vCell = mGrid[0][0];
 preserve_filter_and_order(x,vCell,vIndices);
 return vIndices;
}
bool Frame::PosInGrid(const cv::KeyPoint& k) { return false; }
}
'''


def test_capacity_and_cell_storage_only():
    prod,fixture,original=extract_grid(SOURCE)
    assert original in prod.replace('const vector<size_t>& vCell =','const vector<size_t> vCell =').replace('vIndices.reserve(std::min(N,64));','vIndices.reserve(N);')
    assert 'preserve_filter_and_order(x,vCell,vIndices);' in fixture
    assert 'const auto& mGrid=self.mGrid;' in fixture


@pytest.mark.parametrize('source',[SOURCE+SOURCE,SOURCE.replace('vIndices.reserve(N);','upstream_storage_changed();'),SOURCE.replace('bool Frame::PosInGrid(','bool Frame::OtherBoundary(')])
def test_unreviewed_upstream_grid_source_rejected(source):
    with pytest.raises(ValueError):extract_grid(source)
