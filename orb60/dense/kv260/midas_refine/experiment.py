"""Independent PTQ sensitivity experiments. Higher precision cases are diagnosis only."""
import argparse
import json
import shutil
import inspect
import math
from pathlib import Path
import numpy as np
from ..common import load_midas,read_tensor,save,digest,INPUT_SHAPE
from ..metrics import evaluate


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',required=True,
        choices=['int8-no-bias-correction','weights16','activations16','all16','wide16-no-bias','act-range2','act-range4','params-range2','saturation','bias-safe','bias-safe-mincalib'])
    a=p.parse_args()
    import torch
    from pytorch_nndct.apis import torch_quantizer
    from nndct_shared.utils import NndctOption
    torch.set_num_threads(2)
    NndctOption.nndct_relu6_replace.value='reluk'
    NndctOption.nndct_equalization.value=True
    NndctOption.nndct_convert_relu6_to_relu.value=False
    NndctOption.nndct_quant_off.value=False
    NndctOption.nndct_param_corr.value=a.case not in ['int8-no-bias-correction','wide16-no-bias']
    root=Path('orb60/build');base=root/('kv260/midas_refine/realkeyframes-min' if a.case=='bias-safe-mincalib' else 'kv260/quantized_reluk');out=root/'kv260/midas_refine'/a.case
    out.mkdir(parents=True,exist_ok=True)
    config=json.loads((base/'quant_info.json').read_text())
    for group,entries in config.items():
        if not isinstance(entries,dict):continue
        promote=(group=='param' and a.case in ['weights16','all16','wide16-no-bias']) or (group in ['output','input'] and a.case in ['activations16','all16','wide16-no-bias'])
        if promote:
            for name,value in entries.items():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],int):
                    value[0]=16;value[1]+=4 if a.case=='wide16-no-bias' else 8
        if (group in ['output','input'] and a.case in ['act-range2','act-range4']) or (group=='param' and a.case=='params-range2'):
            for value in entries.values():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],int):value[1]-=2 if a.case=='act-range4' else 1
    save(out/'quant_info.json',config)
    if (base/'bias_corr.pth').exists():shutil.copyfile(base/'bias_corr.pth',out/'bias_corr.pth')
    report={'case':a.case,'status':'RUNNING','hardware_verified':False,'dpu_deployable':False,
            'source_config_sha256':digest(base/'quant_info.json'),'experiment_config_sha256':digest(out/'quant_info.json'),'frames':[]}
    save(out/'result.json',report)
    try:
        samples=root/'dense/samples-midas';frames=json.loads((samples/'samples.json').read_text())['frames']
        model=load_midas(root/'dense/assets',static_padding=True)
        x=read_tensor(samples/'kf_00.input.f32',INPUT_SHAPE)
        q=torch_quantizer('test',model,(torch.from_numpy(x),),output_dir=str(out),bitwidth=8,device=torch.device('cpu'))
        if a.case in ['saturation','bias-safe','bias-safe-mincalib']:
            original=q.processor.quantizer.do_quantize;signature=inspect.signature(original);saturation={}
            def measure(*args,**kwargs):
                bound=signature.bind_partial(*args,**kwargs);bound.apply_defaults();v=bound.arguments
                tensor=next((z for z in args if isinstance(z,torch.Tensor)),None)
                name=v.get('name');group=v.get('tensor_type','output')
                if tensor is not None and name is not None:
                    cfg=q.processor.quantizer.get_quant_config(name,real_value=False,tensor_type=group)
                    if cfg and len(cfg)==2 and cfg[1] is not None:
                        if a.case.startswith('bias-safe') and group=='param' and name.endswith('.bias'):
                            extent=float(tensor.abs().max())
                            safe=int(math.floor(math.log2(127./extent))) if extent>0 else cfg[1]
                            if safe<cfg[1]:
                                report.setdefault('bias_range_changes',[]).append({'name':name,'before':cfg[1],'after':safe,'maximum_abs':extent})
                                q.processor.quantizer.set_quant_config(name,[8,safe],tensor_type=group)
                                cfg=[8,safe]
                        bits,fp=cfg;step=2.**(-fp);lo=(-2**(bits-1)-.5)*step;hi=(2**(bits-1)-.5)*step
                        count=int(((tensor<lo)|(tensor>=hi)).sum());key=group+':'+name
                        row=saturation.setdefault(key,{'group':group,'name':name,'bitwidth':bits,'fix_point':fp,'clipped':0,'values':0,'worst_fraction':0.,'minimum':float('inf'),'maximum':-float('inf')})
                        row['clipped']+=count;row['values']+=tensor.numel();row['worst_fraction']=max(row['worst_fraction'],count/tensor.numel())
                        row['minimum']=min(row['minimum'],float(tensor.min()));row['maximum']=max(row['maximum'],float(tensor.max()))
                return original(*args,**kwargs)
            q.processor.quantizer.do_quantize=measure
        for f in frames:
            x=read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE)
            if digest(samples/(f['id']+'.input.f32'))!=f['input_sha256']:raise ValueError('Input hash mismatch')
            with torch.no_grad():value=q.quant_model(torch.from_numpy(x)).numpy().reshape(256,256)
            reference=np.load(root/'dense/midas-small-fp16'/(f['id']+'.reference.npy'))
            row={'id':f['id'],**evaluate(reference,value)};row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98
            report['frames'].append(row);print('SENSITIVITY',a.case,row,flush=True)
        report.update(status='DIAGNOSTIC_COMPLETE',passed=sum(f['passed'] for f in report['frames']),
                      worst_nrmse=max(f['normalized_rmse'] for f in report['frames']),minimum_spearman=min(f['spearman'] for f in report['frames']))
        if a.case in ['saturation','bias-safe','bias-safe-mincalib']:save(out/'saturation.json',sorted(saturation.values(),key=lambda x:x['worst_fraction'],reverse=True))
        if a.case.startswith('bias-safe'):
            save(out/'actual_quant_config.json',q.processor.quantizer.quant_config)
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(out/'result.json',report);raise
    save(out/'result.json',report)

if __name__=='__main__':main()
