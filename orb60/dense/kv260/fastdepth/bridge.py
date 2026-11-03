"""PS-side boundary adapter: fixed external ORB pipeline contract, native FastDepth shape."""
from pathlib import Path
import json
import cv2
import numpy as np
from ..common import INPUT_SHAPE,digest
from ..tensors import quantize,dequantize


def to_native(x):
    x=np.asarray(x,dtype=np.float32)
    if x.shape!=INPUT_SHAPE or not np.isfinite(x).all():raise ValueError('Invalid external FastDepth input')
    rgb=x[0].transpose(1,2,0)*np.array([.229,.224,.225],np.float32)+np.array([.485,.456,.406],np.float32)
    rgb=cv2.resize(np.clip(rgb,0,1),(224,224),interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(rgb.transpose(2,0,1)[None])


def to_inverse(depth):
    depth=np.asarray(depth,dtype=np.float32).reshape(224,224)
    if not np.isfinite(depth).all():raise ValueError('Nonfinite FastDepth prediction')
    valid=depth>1e-6
    up=cv2.resize(depth,(256,256),interpolation=cv2.INTER_LINEAR)
    mask=cv2.resize(valid.astype(np.float32),(256,256),interpolation=cv2.INTER_LINEAR)>.999
    inverse=np.zeros((256,256),np.float32)
    good=mask&(up>1e-6);inverse[good]=1/up[good]
    return inverse


class Reference:
    def __init__(self,model):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=4
        self.session=ort.InferenceSession(str(model),options,providers=['CPUExecutionProvider'])
        if self.session.get_inputs()[0].shape!=[1,3,224,224]:raise ValueError('Expected native 224x224 model')
    def native(self,x):return self.session.run(None,{self.session.get_inputs()[0].name:to_native(x)})[0]
    def __call__(self,x):return to_inverse(self.native(x))


class QuantizedReference:
    def __init__(self,model):
        import torch
        from pytorch_nndct.apis import torch_quantizer
        from nndct_shared.utils import NndctOption
        from ..quant_config import validate_quant_config
        from .model import FastDepth
        torch.set_num_threads(4);self.torch=torch;root=Path(model).parent
        spec=json.loads(Path(model).read_text());source=(root/spec['source_onnx']).resolve()
        if digest(source)!=spec['source_sha256'] or digest(root/'quant_info.json')!=spec['quant_config_sha256']:raise ValueError('FastDepth quantizer identity mismatch')
        if (digest(root/'bias_corr.pth') if (root/'bias_corr.pth').exists() else None)!=spec.get('bias_correction_sha256'):raise ValueError('FastDepth bias correction mismatch')
        validate_quant_config(json.loads((root/'quant_info.json').read_text()))
        NndctOption.nndct_equalization.value=bool(spec.get('equalization',False));NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_convert_relu6_to_relu.value=False;NndctOption.nndct_quant_off.value=False
        NndctOption.nndct_param_corr.value=bool(spec.get('parameter_correction',True))
        self.quantizer=torch_quantizer('test',FastDepth(source),(torch.zeros(1,3,224,224),),output_dir=str(root),bitwidth=8,device=torch.device('cpu'))
        self.model=self.quantizer.quant_model.eval()
    def __call__(self,x):
        with self.torch.no_grad():return to_inverse(self.model(self.torch.from_numpy(to_native(x))).detach().numpy())


def dpu_forward(engine,x):
    target=np.asarray(engine.inputs[0]);native=to_native(x)
    value=native.transpose(0,2,3,1) if target.shape==(1,224,224,3) else native
    if value.shape!=target.shape:raise ValueError('FastDepth DPU input layout mismatch')
    tensor=engine.inputs[0].get_tensor()
    if target.dtype==np.int8:value=quantize(value,tensor.get_attr('fix_point'))
    elif target.dtype!=np.float32:raise ValueError('FastDepth DPU input dtype mismatch')
    target[:]=value;job=engine.runner.execute_async(engine.inputs,engine.outputs)
    if engine.runner.wait(job)!=0:raise RuntimeError('FastDepth VART failed')
    result=np.asarray(engine.outputs[0]).copy();tensor=engine.outputs[0].get_tensor()
    if result.dtype==np.int8:result=dequantize(result,tensor.get_attr('fix_point'))
    elif result.dtype!=np.float32:raise ValueError('FastDepth output dtype mismatch')
    return to_inverse(result)
