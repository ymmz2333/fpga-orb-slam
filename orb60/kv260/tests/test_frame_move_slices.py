import pytest
from orb60.kv260.ps.compose_frame_move_slices import extract

SOURCE='''// license
#include "Kv260DepthKeyframesImpl.h"
#include "BridgeTrackingDiagnosticsImpl.h"
namespace ORB_SLAM3 {
void Tracking::Track() {
 const char* text="brace } { and // text";
 char close='}'; /* { ignored */
 // } ignored
 if(keep_decision()) { preserve_geometry(); }
}
void Tracking::Following() { other(); }
}
'''


def test_function_slice_preserves_body_and_keeps_single_shared_state_definition():
    produced,body=extract(SOURCE,'Track')
    assert body in SOURCE and body in produced
    assert body.endswith('if(keep_decision()) { preserve_geometry(); }\n}')
    assert 'Impl.h' not in produced
    assert '#include "Kv260DepthKeyframes.h"' in produced
    assert '#include "BridgeTrackingDiagnostics.h"' in produced
    assert 'Following' not in produced


@pytest.mark.parametrize('method',[
    'void Tracking::Track() { preserve_geometry(); }',
    'void Tracking::Track() { if(keep_decision()) { preserve_geometry(); } tail(); }',
    'void Tracking::Track()\n{\n preserve_geometry();\n}',
])
def test_opening_brace_on_same_or_following_line_preserves_entire_method(method):
    prefix=SOURCE[:SOURCE.index('void Tracking::Track()')]
    source=prefix+method+'\nvoid Tracking::Following() { other(); }\n}\n'
    produced,body=extract(source,'Track')
    assert body==method
    assert method in produced
    assert 'Following' not in produced


@pytest.mark.parametrize('source',[SOURCE+SOURCE,SOURCE.replace('void Tracking::Track()','void Tracking::Changed()'),SOURCE.replace('#include "Kv260DepthKeyframesImpl.h"','// missing boundary')])
def test_unreviewed_method_or_shared_state_boundary_rejected(source):
    with pytest.raises(ValueError):extract(source,'Track')
