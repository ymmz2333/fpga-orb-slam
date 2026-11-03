"""Preserve MiDaS Resize semantics while folding static shape expressions."""
import argparse
from collections import Counter
from pathlib import Path
import onnx
from .common import digest,save

def inspect(model):
    graph=onnx.load(str(model));onnx.checker.check_model(graph)
    resize=[]
    for node in graph.graph.node:
        if node.op_type=='Resize':
            attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
            resize.append({'name':node.name,'mode':attrs.get('mode',b'nearest').decode(),
                           'coordinates':attrs.get('coordinate_transformation_mode',b'half_pixel').decode()})
    return {'sha256':digest(model),'opsets':{x.domain:x.version for x in graph.opset_import},
            'operators':dict(Counter(n.op_type for n in graph.graph.node)), 'resize':resize,
            'inputs':{v.name:[d.dim_value if d.HasField('dim_value') else d.dim_param for d in v.type.tensor_type.shape.dim] for v in graph.graph.input},
            'outputs':{v.name:[d.dim_value if d.HasField('dim_value') else d.dim_param for d in v.type.tensor_type.shape.dim] for v in graph.graph.output}}

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);before=inspect(a.model)
    if list(before['inputs'].values())!=[[1,3,256,256]]:raise ValueError('Expected fixed RGB/NCHW input')
    if sum(x['coordinates']=='align_corners' for x in before['resize'])!=4:raise ValueError('Unexpected retained MiDaS graph')
    from onnxsim import simplify
    graph,checked=simplify(str(a.model),check_n=3,perform_optimization=True)
    if not checked:raise RuntimeError('Static folding equivalence failed')
    target=a.output/'midas_static.onnx';onnx.save(graph,str(target));after=inspect(target)
    if before['resize']!=after['resize']:raise ValueError('Resize semantics changed')
    save(a.output/'model_inspection.json',{'status':'STATIC_GRAPH_PASS','original':before,'folded':after,
         'hardware_placement':'NOT_COMPILED','ps_candidates':['Resize align_corners','tensor layout/quantization'],
         'all_convolution_must_be_dpu':True})
    print('STATIC_GRAPH_PASS',after['operators'])

if __name__=='__main__':main()
