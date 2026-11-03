"""Verify fixed MiDaS semantics against the original twenty frozen predictions."""
import argparse
import json
from pathlib import Path
import numpy as np
from .common import digest,load_midas,read_tensor,save,INPUT_SHAPE
from .worker import Reference
from .metrics import evaluate


def main():
    p=argparse.ArgumentParser()
    for key in ['assets','samples','reference','model','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    import torch
    torch.set_num_threads(4)
    model=load_midas(a.assets);engine=Reference(a.model)
    manifest=json.loads((a.samples/'samples.json').read_text());results=[]
    if len(manifest['frames'])!=20:raise ValueError('Expected twenty frozen samples')
    a.output.mkdir(parents=True,exist_ok=True)
    torch.onnx.export(model,torch.zeros(INPUT_SHAPE),str(a.output/'midas_reexport.onnx'),
                      input_names=['rgb'],output_names=['inverse_depth'],opset_version=13,
                      do_constant_folding=True)
    reexport=Reference(a.output/'midas_reexport.onnx')
    for frame in manifest['frames']:
        name=frame['id'];path=a.samples/(name+'.input.f32');x=read_tensor(path,INPUT_SHAPE)
        if digest(path)!=frame['input_sha256']:raise ValueError('Frozen input hash mismatch')
        frozen=np.load(a.reference/(name+'.reference.npy')).reshape(256,256)
        with torch.no_grad():eager=model(torch.from_numpy(x)).numpy().reshape(256,256)
        outputs={'eager':eager,'static_onnx':engine(x),'reexport_onnx':reexport(x)}
        row={'id':name,'input_sha256':digest(path),'results':{}}
        for kind,value in outputs.items():
            error=float(np.max(np.abs(value-frozen)));limit=.002*max(1.,float(frozen.max()))
            row['results'][kind]={'max_abs_error':error,'limit':limit,'passed':error<=limit,**evaluate(frozen,value)}
        results.append(row);print('FLOAT_CHECK',name,flush=True)
    save(a.output/'float_gate.json',{'status':'FLOAT_PASS' if all(v['passed'] for r in results for v in r['results'].values()) else 'FAILED',
         'weight_sha256':digest(a.assets/'midas_v21_small_256.pt'),'static_model_sha256':digest(a.model),
         'reexport_sha256':digest(a.output/'midas_reexport.onnx'),'frames':results,'hardware_inference_verified':False})
    if not all(v['passed'] for r in results for v in r['results'].values()):raise SystemExit(1)

if __name__=='__main__':main()
