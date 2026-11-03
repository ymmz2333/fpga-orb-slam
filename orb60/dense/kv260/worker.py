"""Four-argument worker: MODEL INPUT_DIR NAMES_OR_DASH OUTPUT_DIR, explicit backend."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from .common import INPUT_SHAPE,OUTPUT_SHAPE,checked_id,digest,read_tensor,write_tensor,save,output_lock
from .tensors import pack_input,unpack_output

class Reference:
    def __init__(self,model):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=4
        self.session=ort.InferenceSession(str(model),options,providers=['CPUExecutionProvider'])
        if self.session.get_inputs()[0].shape!=list(INPUT_SHAPE):raise ValueError('Reference model input mismatch')
    def __call__(self,x):return self.session.run(None,{self.session.get_inputs()[0].name:x})[0].reshape(OUTPUT_SHAPE)

class QuantizedReference:
    def __init__(self,model):
        import torch
        self.torch=torch;torch.set_num_threads(4)
        if Path(model).suffix=='.json':
            from pytorch_nndct.apis import torch_quantizer
            from nndct_shared.utils import NndctOption
            NndctOption.nndct_relu6_replace.value='reluk'
            NndctOption.nndct_equalization.value=False
            NndctOption.nndct_convert_relu6_to_relu.value=False
            NndctOption.nndct_quant_off.value=False
            from .common import load_midas
            specification=json.loads(Path(model).read_text());root=Path(model).parent
            policy=specification.get('policy',{})
            recipe=policy.get('recipe')
            if recipe is None and policy.get('static_same_padding') is True and policy.get('relu6')=='native ReLU6 retained' and policy.get('equalization') is False:recipe='native-static'
            if recipe not in {'native-static','reluk-cle'}:raise ValueError('Unsupported quantization recipe')
            NndctOption.nndct_equalization.value=recipe=='reluk-cle'
            assets=(root/specification['assets']).resolve()
            if digest(assets/'midas_v21_small_256.pt')!=specification['weight_sha256'] or digest(root/'quant_info.json')!=specification['quant_config_sha256']:
                raise ValueError('Quantized reference specification mismatch')
            from .quant_config import validate_quant_config
            validate_quant_config(json.loads((root/'quant_info.json').read_text()))
            correction=root/'bias_corr.pth'
            if (digest(correction) if correction.exists() else None)!=specification.get('bias_correction_sha256'):raise ValueError('Bias correction hash mismatch')
            if specification.get('policy',{}).get('static_same_padding') is not True:raise ValueError('Unsupported quantization recipe')
            quantizer=torch_quantizer('test',load_midas(assets,static_padding=True),(torch.zeros(INPUT_SHAPE),),
                                     output_dir=str(root),bitwidth=8,device=torch.device('cpu'))
            self.model=quantizer.quant_model.eval();self.quantizer=quantizer
        else:
            self.model=torch.jit.load(str(model),map_location='cpu').eval()
    def __call__(self,x):
        with self.torch.inference_mode():return self.model(self.torch.from_numpy(x)).detach().cpu().numpy().reshape(OUTPUT_SHAPE)

class Dpu:
    def __init__(self,model,proof,placement):
        # Both fingerprint queries and runners must use already loaded hardware.
        os.environ['XLNX_DISABLE_LOAD_XCLBIN']='1'
        import platform
        if platform.machine()!='aarch64':raise RuntimeError('DPU backend requires KV260, never host fallback')
        proof=json.loads(Path(proof).read_text());placed=json.loads(Path(placement).read_text())
        driver=proof.get('driver','xrt')
        if driver not in ('xrt','vivado'):raise ValueError('Unknown DPU hardware control ABI')
        self.driver=driver
        if driver=='vivado':os.environ['DISABLE_DPU_CONTROLLER_XRT']='1'
        if proof.get('status')!='PROFILE_MATCH':raise ValueError('Successful read-only preflight required')
        if proof.get('machine')!='aarch64' or proof.get('os',{}).get('VERSION_ID')!='22.04':raise ValueError('Wrong preflight OS/machine')
        if placed.get('status')!='COMPILE_PLACEMENT_PASS' or placed.get('model_sha256')!=digest(model):raise ValueError('Matching placement report required')
        if placed.get('explicit_ps_operator_policy',{}).get('approved_extra_ops'):
            import ctypes
            self.ps_relu_runtime=ctypes.CDLL('libvart_op_imp_relu.so')
            bound=self.ps_relu_runtime.kv260_ps_relu_model_sha256;bound.restype=ctypes.c_char_p
            if bound().decode()!=digest(model):raise ValueError('PS ReLU runtime belongs to another model')
        import xir
        from vitis_ai_library import GraphRunner
        self.graph=xir.Graph.deserialize(str(model))
        # Re-query the actual running device; a copied/stale preflight JSON is insufficient.
        from .preflight import fingerprints,check_xrt,query_current_device
        current=query_current_device(driver)
        check_xrt(current,proof.get('expected_xrt_prefix'))
        if not set(placed.get('fingerprints',[])) or not set(placed['fingerprints']).issubset(fingerprints(current)):
            raise ValueError('Compiled graph fingerprint does not match current DPU')
        if not set(placed['fingerprints']).issubset(set(proof.get('fingerprints',[]))):raise ValueError('Preflight/model fingerprint mismatch')
        self.runner=GraphRunner.create_graph_runner(self.graph)
        self.inputs=self.runner.get_inputs();self.outputs=self.runner.get_outputs()
        if len(self.inputs)!=1 or len(self.outputs)!=1:raise ValueError('Expected single input and output')
    def __call__(self,x):
        target=np.asarray(self.inputs[0]);tensor=self.inputs[0].get_tensor()
        fix=tensor.get_attr('fix_point') if tensor.has_attr('fix_point') else None
        target[:]=pack_input(x,target.shape,target.dtype,fix)
        job=self.runner.execute_async(self.inputs,self.outputs)
        if self.runner.wait(job)!=0:raise RuntimeError('VART execution failed')
        tensor=self.outputs[0].get_tensor();fix=tensor.get_attr('fix_point') if tensor.has_attr('fix_point') else None
        return unpack_output(np.asarray(self.outputs[0]),fix)

def run(model,inputs,names,output,backend,preflight=None,placement=None,family='midas'):
    with output_lock(output):return _run(model,inputs,names,output,backend,preflight,placement,family)


def _run(model,inputs,names,output,backend,preflight=None,placement=None,family='midas'):
    if backend not in {'reference','quantized-reference','dpu'}:raise ValueError('Explicit valid backend required')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report={'backend':backend,'family':family,'model_sha256':digest(model),'status':'RUNNING','hardware_inference_verified':False,'frames':[]}
    save(output/'worker.json',report)
    try:
        if family=='fastdepth':
            from .fastdepth.bridge import Reference as FastReference,QuantizedReference as FastQuantized,dpu_forward
            engine={'reference':FastReference,'quantized-reference':FastQuantized}.get(backend)
            if engine:engine=engine(model)
            else:
                hardware=Dpu(model,preflight,placement)
                engine=lambda x:dpu_forward(hardware,x)
        elif family=='midas':
            engine={'reference':Reference,'quantized-reference':QuantizedReference}.get(backend)
            engine=engine(model) if engine else Dpu(model,preflight,placement)
        else:raise ValueError('Unknown depth family')
        if backend=='dpu':report['hardware_driver']=json.loads(Path(preflight).read_text()).get('driver','xrt')
        stream=sys.stdin if str(names)=='-' else Path(names).open(encoding='utf-8')
        seen=set();expected=None
        manifest=Path(inputs)/'names.txt'
        if manifest.is_file():expected=[checked_id(n) for n in manifest.read_text().splitlines()]
        try:
            for line in stream:
                name=checked_id(line.strip())
                if name in seen:raise ValueError('Duplicate/out-of-order frame ID: '+name)
                if expected is not None and (len(seen)>=len(expected) or name!=expected[len(seen)]):raise ValueError('Frame ordering differs from input manifest')
                seen.add(name);x=read_tensor(Path(inputs)/(name+'.input.f32'),INPUT_SHAPE)
                source=digest(Path(inputs)/(name+'.input.f32'));prior=output/(name+'.frame.json')
                identity={'input_sha256':source,'model_sha256':report['model_sha256'],'backend':backend}
                if prior.exists():
                    old=json.loads(prior.read_text())
                    if any(old.get(k)!=v for k,v in identity.items()):raise ValueError('Resume identity mismatch')
                    path=output/(name+'.output.f32');read_tensor(path,OUTPUT_SHAPE)
                    if digest(path)!=old['output_sha256']:raise ValueError('Corrupted resumed output')
                    record=old.copy();record['reused']=True
                else:
                    tick=time.perf_counter();value=engine(x);elapsed=time.perf_counter()-tick
                    path=output/(name+'.output.f32');write_tensor(path,value)
                    record={'id':name,**identity,'seconds':elapsed,'output_sha256':digest(path),'reused':False}
                    save(prior,record)
                report['frames'].append(record);save(output/'worker.json',report)
                print('DEPTH_FRAME',name,'backend='+backend,flush=True)
        finally:
            if stream is not sys.stdin:stream.close()
        if not report['frames']:raise ValueError('Empty input list')
        if expected is not None and len(seen)!=len(expected):raise ValueError('Input stream ended before complete manifest')
        report['status']='DPU_RUN_REQUIRES_NUMERICAL_GATE' if backend=='dpu' else 'HOST_REFERENCE_PASS'
        report['hardware_inference_verified']=backend=='dpu'
    except Exception as e:
        report.update(status='FAILED',error=str(e));save(output/'worker.json',report);raise
    save(output/'worker.json',report);return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['model','inputs','names','output']:p.add_argument(name,type=Path)
    p.add_argument('--backend',required=True,choices=['reference','quantized-reference','dpu'])
    p.add_argument('--preflight',type=Path);p.add_argument('--placement',type=Path)
    p.add_argument('--family',choices=['midas','fastdepth'],default='midas')
    a=p.parse_args();run(**vars(a))

if __name__=='__main__':main()
