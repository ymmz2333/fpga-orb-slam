import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
import torch
from orb60.dense.kv260.common import INPUT_SHAPE,OUTPUT_SHAPE,checked_id,preprocess,read_tensor,save,write_tensor,output_lock
from orb60.dense.kv260.tensors import quantize,dequantize,resize_nchw,to_nchw,to_nhwc,pack_input,unpack_output
from orb60.dense.kv260.preflight import validate,check_xrt
from orb60.dense.kv260.placement import validate_placement
from orb60.dense.kv260.prepare_replay import validate_manifest
from orb60.dense.kv260 import worker


@pytest.mark.parametrize('align',[True,False])
@pytest.mark.parametrize('size',[(1,1),(7,13),(2,2),(6,10)])
def test_resize_matches_torch(align,size):
    x=np.random.RandomState(42).randn(2,3,3,5).astype(np.float32)
    expected=torch.nn.functional.interpolate(torch.from_numpy(x),size=size,mode='bilinear',align_corners=align).numpy()
    np.testing.assert_allclose(resize_nchw(x,size,align),expected,atol=7e-7,rtol=2e-6)


def test_quantization_boundaries_and_layout():
    x=np.array([-100,-1.5,-.5,.5,1.5,100],np.float32)
    np.testing.assert_array_equal(quantize(x,1),[-128,-3,-1,1,3,127])
    np.testing.assert_array_equal(quantize(np.array([-1.5,-.5,.5,1.5]),0),[-1,0,1,2])
    values=np.arange(np.prod(INPUT_SHAPE),dtype=np.float32).reshape(INPUT_SHAPE)/1000
    np.testing.assert_array_equal(to_nchw(to_nhwc(values)),values)
    packed=pack_input(values,(1,256,256,3),np.int8,2)
    np.testing.assert_array_equal(packed,quantize(to_nhwc(values),2))
    np.testing.assert_array_equal(unpack_output(np.ones((1,256,256,1),np.int8),3),np.full(OUTPUT_SHAPE,.125))
    for shape,dtype,fix in [((1,256,256,3),np.int8,None),((3,256,256),np.float32,None),((1,3,256,256),np.int16,1)]:
        with pytest.raises(ValueError):pack_input(values,shape,dtype,fix)
    with pytest.raises(ValueError):quantize([np.nan],1)


def test_rgb_preprocessing_and_bad_files(tmp_path):
    rgb=np.full((17,31,3),(255,0,0),np.uint8);value=preprocess(rgb)
    np.testing.assert_allclose(value[0,:,0,0],[(1-.485)/.229,-.456/.224,-.406/.225],atol=1e-6)
    for x in [np.zeros((3,17,31),np.uint8),rgb.astype(float)]:
        with pytest.raises(ValueError):preprocess(x)
    path=tmp_path/'x';path.write_bytes(b'broken')
    with pytest.raises(ValueError):read_tensor(path,OUTPUT_SHAPE)
    np.full(OUTPUT_SHAPE,np.nan,np.float32).tofile(path)
    with pytest.raises(ValueError):read_tensor(path,OUTPUT_SHAPE)
    with pytest.raises(ValueError):write_tensor(path,np.ones((2,2)))
    for name in ['../x','x/y','','a b']:
        with pytest.raises(ValueError):checked_id(name)


def test_output_ownership_and_metric_equivalence(tmp_path):
    from orb60.dense.kv260.metrics import evaluate as current
    from orb60.dense.scripts.evaluate_npu_gate import evaluate as retained
    x=np.arange(100).reshape(10,10);y=x+.1*np.sin(x)
    assert current(x,y)==retained(x,y)
    with output_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with output_lock(tmp_path):pass
    with output_lock(tmp_path):pass


def test_all_parameters_have_real_int8_calibration():
    from orb60.dense.kv260.quant_config import validate_quant_config
    assert validate_quant_config({'param':{'conv.weight':[8,5]}})==1
    for config in [{},{'param':{'conv.weight':[8,None]}},{'param':{'conv.weight':[16,5]}}]:
        with pytest.raises(ValueError):validate_quant_config(config)


def test_preflight_rejects_host_and_wrong_platform():
    release={'ID':'ubuntu','VERSION_ID':'22.04'};query={'DPU fingerprint':'0x101'};arch={'fingerprint':'0x101'}
    assert validate(release,'aarch64',query,arch,'2.5.0')==['0x101']
    assert validate(release,'aarch64',query,arch,'libvart-runner.so.2.5.0')==['0x101']
    assert validate(release,'aarch64',query,arch,'Xilinx vart-runner Version: 2.5.0-c26eae36 2026-11-02')==['0x101']
    for os,cpu,q,a,v in [(release,'x86_64',query,arch,'2.5'),(release,'aarch64',query,{'fingerprint':'0x102'},'2.5'),
                          ({**release,'VERSION_ID':'20.04'},'aarch64',query,arch,'2.5'),(release,'aarch64',query,arch,'3.0')]:
        with pytest.raises(RuntimeError):validate(os,cpu,q,a,v)
    assert check_xrt({'libxrt_core.so':'libxrt_core.so.2.13.0'},'2.13')==['2.13.0']
    assert check_xrt({'XRT':{'version':'2.13.0'}},'2.13')==['2.13.0']
    for value,expected in [({},'2.13'),({'xrt':'2.14.0'},'2.13'),({'xrt':'2.13.0'},None)]:
        with pytest.raises(RuntimeError):check_xrt(value,expected)


def test_native_xrt_version_output_is_explicit_and_unambiguous():
    from orb60.dense.kv260.preflight import parse_xrt_version
    assert parse_xrt_version('Version              : 2.13.0\nHash : abc\nZOCL : 2.13.0, \n')=='2.13.0'
    for text in ('ZOCL : 2.13.0\n','Version : unknown\n','Version : 2.13.0\nVersion : 2.14.0\n'):
        with pytest.raises(RuntimeError):parse_xrt_version(text)


def test_placement_never_hides_cpu_convolution():
    dpu={'device':'DPU','ops':[{'name':'backbone','type':'conv2d-fix'}]}
    cpu={'device':'CPU','ops':[{'name':'upsample','type':'resize'}]}
    assert validate_placement([dpu,cpu])['convolutions']==1
    fixed={'device':'CPU','ops':[{'name':'input','type':'data-fix'},{'name':'resize','type':'upsample-fix'}]}
    assert validate_placement([dpu,fixed])['convolutions']==1
    for bad in [[],[cpu],[dpu,{'device':'CPU','ops':[{'name':'c','type':'conv2d'}]}],
                [dpu,{'device':'CPU','ops':[{'name':'a','type':'sigmoid'}]}]]:
        with pytest.raises(ValueError):validate_placement(bad)


class FakeReference:
    def __init__(self,model):pass
    def __call__(self,x):return np.full(OUTPUT_SHAPE,float(x.mean()),np.float32)


def test_worker_resume_order_corruption_and_backend(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'Reference',FakeReference)
    model=tmp_path/'model.onnx';model.write_bytes(b'model');inputs=tmp_path/'inputs';inputs.mkdir();output=tmp_path/'outputs'
    for name in ['a','b']:np.ones(INPUT_SHAPE,np.float32).tofile(inputs/(name+'.input.f32'))
    names=inputs/'names.txt';names.write_text('a\nb\n')
    report=worker.run(model,inputs,names,output,'reference');assert report['status']=='HOST_REFERENCE_PASS'
    report=worker.run(model,inputs,names,output,'reference');assert all(f['reused'] for f in report['frames'])
    wrong=tmp_path/'wrong.txt';wrong.write_text('b\na\n')
    with pytest.raises(ValueError,match='ordering'):worker.run(model,inputs,wrong,output,'reference')
    assert json.loads((output/'worker.json').read_text())['status']=='FAILED'
    (output/'a.output.f32').write_bytes(b'x')
    with pytest.raises(ValueError):worker.run(model,inputs,names,output,'reference')
    with pytest.raises(ValueError):worker.run(model,inputs,names,output,'automatic')


def test_subprocess_stream_failure_and_restart(tmp_path):
    # A real ONNX Runtime subprocess exercises process failure and per-frame recovery.
    import onnx
    from onnx import helper,TensorProto
    nodes=[helper.make_node('ReduceMean',['rgb'],['mean'],keepdims=0),helper.make_node('Expand',['mean','shape'],['depth'])]
    shape=onnx.numpy_helper.from_array(np.array([1,256,256],np.int64),'shape')
    graph=helper.make_graph(nodes,'contract',[helper.make_tensor_value_info('rgb',TensorProto.FLOAT,list(INPUT_SHAPE))],
                            [helper.make_tensor_value_info('depth',TensorProto.FLOAT,[1,256,256])],[shape])
    model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',13)]);model.ir_version=9
    path=tmp_path/'tiny.onnx';onnx.save(model,path)
    inp=tmp_path/'inputs';inp.mkdir();out=tmp_path/'output'
    for name in ['a','b']:np.ones(INPUT_SHAPE,np.float32).tofile(inp/(name+'.input.f32'))
    args=[sys.executable,'-m','orb60.dense.kv260.worker',str(path),str(inp),'-',str(out),'--backend','reference']
    failed=subprocess.run(args,input='a\n../bad\n',text=True,capture_output=True,timeout=30)
    assert failed.returncode!=0 and 'DEPTH_FRAME a' in failed.stdout
    assert json.loads((out/'worker.json').read_text())['status']=='FAILED'
    recovered=subprocess.run(args,input='a\nb\n',text=True,capture_output=True,timeout=30)
    assert recovered.returncode==0,recovered.stderr
    report=json.loads((out/'worker.json').read_text());assert report['frames'][0]['reused']
    assert not report['hardware_inference_verified']


def test_manifest_integer_timestamps_and_poses():
    frame={'map_id':0,'keyframe_id':0,'timestamp_ns':1,'twc':np.eye(4).tolist(),'k':np.eye(3).tolist()}
    valid={'maps':[{'map_id':0,'frames':[frame]}]};validate_manifest(valid)
    for wrong in [{**frame,'timestamp_ns':1.0},{**frame,'twc':np.zeros((4,4)).tolist()}]:
        with pytest.raises(ValueError):validate_manifest({'maps':[{'map_id':0,'frames':[wrong]}]})
    with pytest.raises(ValueError):validate_manifest({'maps':[{'map_id':0,'frames':[frame,frame]}]})
