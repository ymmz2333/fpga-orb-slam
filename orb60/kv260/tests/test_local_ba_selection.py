"""Fail closed when a retained optimizer no longer has the reviewed boundary."""
import pytest
from orb60.kv260.ps.compile_local_ba_cross import extract


SOURCE = '''#include "Optimizer.h"
namespace ORB_SLAM3 {
void Optimizer::LocalBundleAdjustment(KeyFrame *pKF, bool* stop) {
    const auto neighbors = pKF->GetVectorCovisibleKeyFrames();
    preserve_fixed_observers_and_all_residuals(neighbors, stop);
}
void Optimizer::OptimizeEssentialGraph(Map* pMap) {}
}
'''


def test_window_changes_only_neighbor_selection():
    result, original = extract(SOURCE, 10)
    assert result.replace('GetBestCovisibilityKeyFrames(10)', 'GetVectorCovisibleKeyFrames()') == (
        '#include "Optimizer.h"\nnamespace ORB_SLAM3 {\n' + original + '\n}\n')
    assert 'preserve_fixed_observers_and_all_residuals(neighbors, stop);' in result


@pytest.mark.parametrize('neighbors', [True, 0, -1, 11, 100])
def test_unreviewed_graph_window_is_rejected(neighbors):
    with pytest.raises(ValueError):
        extract(SOURCE, neighbors)


@pytest.mark.parametrize('source', [
    SOURCE.replace('GetVectorCovisibleKeyFrames()', 'ChangedUpstreamSelection()'),
    SOURCE.replace('void Optimizer::OptimizeEssentialGraph', 'void Optimizer::ChangedBoundary'),
    SOURCE.replace('    const auto neighbors', '    const auto duplicate = pKF->GetVectorCovisibleKeyFrames();\n    const auto neighbors'),
    SOURCE + SOURCE,
])
def test_changed_or_ambiguous_upstream_source_is_rejected(source):
    with pytest.raises(ValueError):
        extract(source, 10)
