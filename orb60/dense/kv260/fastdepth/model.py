"""Reconstruct the verified FastDepth ONNX using only ordinary PyTorch operators."""
from pathlib import Path
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
import json
from ..common import digest

MODEL_MD5='7280fe93079cfa5fff03c0ac056f6dce'
MODEL_SHA256='7a9f571d9496555bbcc9c46dcb77f1357fb84d3f2608cd38af91fe66c96dfe85'


def read_graph(path):
    path=Path(path);index=path.with_suffix('.graph.json');weights=path.with_suffix('.weights.npz')
    if not index.exists():
        import onnx
        graph=onnx.load(str(path));onnx.checker.check_model(graph)
        constants={v.name:onnx.numpy_helper.to_array(v).copy() for v in graph.graph.initializer}
        np.savez_compressed(weights,**constants)
        nodes=[]
        for node in graph.graph.node:
            attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
            attrs={k:v.decode() if isinstance(v,bytes) else v for k,v in attrs.items()}
            nodes.append({'kind':node.op_type,'args':list(node.input),'output':node.output[0],'attrs':attrs})
        index.write_text(json.dumps({'onnx_sha256':digest(path),'weights_sha256':digest(weights),
                                    'input':graph.graph.input[0].name,'output':graph.graph.output[0].name,'nodes':nodes}))
    spec=json.loads(index.read_text())
    if spec['onnx_sha256']!=digest(path) or spec['weights_sha256']!=digest(weights):raise ValueError('Frozen ONNX graph/weights hash mismatch')
    with np.load(weights,allow_pickle=False) as archive:constants={k:archive[k].copy() for k in archive.files}
    return spec,constants


class FastDepth(nn.Module):
    def __init__(self,path):
        super().__init__()
        import hashlib
        if digest(path)!=MODEL_SHA256 or hashlib.md5(Path(path).read_bytes()).hexdigest()!=MODEL_MD5:raise ValueError('FastDepth distribution checksum mismatch')
        spec,constants=read_graph(path)
        self.layers=nn.ModuleList();self.steps=[];self.input_name=spec['input'];self.output_name=spec['output']
        for node in spec['nodes']:
            attrs=node['attrs'];args=node['args'];kind=node['kind'];parameter=None
            if kind=='Conv':
                weight=constants[args[1]];bias=constants[args[2]] if len(args)>2 else None;groups=int(attrs.get('group',1))
                pads=attrs.get('pads',[0,0,0,0]);stride=attrs.get('strides',[1,1]);dilation=attrs.get('dilations',[1,1])
                if list(pads[:2])!=list(pads[2:]):raise ValueError('Unexpected asymmetric convolution padding')
                layer=nn.Conv2d(weight.shape[1]*groups,weight.shape[0],tuple(weight.shape[2:]),tuple(stride),tuple(pads[:2]),tuple(dilation),groups,bias is not None)
                layer.weight=nn.Parameter(torch.from_numpy(weight))
                if bias is not None:layer.bias=nn.Parameter(torch.from_numpy(bias))
                parameter=len(self.layers);self.layers.append(layer)
            elif kind=='Clip':
                lo=float(constants[args[1]].ravel()[0]);hi=float(constants[args[2]].ravel()[0])
                if lo!=0 or hi!=6:raise ValueError('Unexpected Clip bounds')
                parameter=len(self.layers);self.layers.append(nn.ReLU6())
            elif kind=='Resize':
                if attrs.get('mode')!='nearest' or attrs.get('coordinate_transformation_mode')!='asymmetric' or attrs.get('nearest_mode')!='floor':
                    raise ValueError('Unsupported FastDepth resize semantics')
                scale=constants[args[2]].tolist()
                if scale!=[1.,1.,2.,2.]:raise ValueError('Unexpected FastDepth scale')
            elif kind not in {'Relu','Add'}:raise ValueError('Unexpected ONNX operator: '+kind)
            self.steps.append((kind,args,node['output'],parameter))
        self.eval()

    def forward(self,x):
        values={self.input_name:x}
        for kind,args,name,parameter in self.steps:
            if kind in {'Conv','Clip'}:value=self.layers[parameter](values[args[0]])
            elif kind=='Relu':value=F.relu(values[args[0]])
            elif kind=='Add':value=values[args[0]]+values[args[1]]
            elif kind=='Resize':value=F.interpolate(values[args[0]],scale_factor=2,mode='nearest')
            values[name]=value
        return values[self.output_name]
