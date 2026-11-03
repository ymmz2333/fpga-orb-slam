import io
from types import SimpleNamespace
import numpy as np
from orb60.kv260.dense_service import DpuDepth


def test_persistent_dpu_request_writes_rgb_nchw_and_reads_exact_depth(tmp_path):
    # Exercise the persistent service boundary without pretending to execute a DPU.
    engine = DpuDepth.__new__(DpuDepth)
    engine.inputs = tmp_path/'inputs';engine.inputs.mkdir()
    engine.outputs = tmp_path/'outputs';engine.outputs.mkdir()
    engine.worker = SimpleNamespace(stdin=io.BytesIO())
    engine.pending = b'DEPTH_FRAME sample backend=dpu\n'
    engine.timeout = 1
    engine.log = io.StringIO()
    expected = np.arange(65536, dtype=np.float32).reshape(256,256)
    expected.tofile(engine.outputs/'sample.output.f32')
    bgr = np.full((720,960,3), [10,20,30], dtype=np.uint8)
    actual = engine.infer('sample', bgr)
    assert np.array_equal(actual, expected)
    assert engine.worker.stdin.getvalue() == b'sample\n'
    value = np.fromfile(engine.inputs/'sample.input.f32', dtype='<f4').reshape(1,3,256,256)
    expected_pixel = (np.array([30,20,10])/255-np.array([.485,.456,.406]))/np.array([.229,.224,.225])
    np.testing.assert_allclose(value[0,:,0,0], expected_pixel, rtol=1e-6)
