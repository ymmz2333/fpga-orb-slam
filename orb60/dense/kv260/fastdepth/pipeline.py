"""Verify and quantize FastDepth against its own frozen FP32 outputs."""
import argparse
import json
import os
from pathlib import Path
import numpy as np
from ..common import INPUT_SHAPE,digest,read_tensor,save
from ..metrics import evaluate
from ..quant_config import validate_quant_config
from .bridge import Reference,to_native,to_inverse


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['float','calib','test'],required=True)
    p.add_argument('--equalization',action='store_true')
    p.add_argument('--no-bias-correction',action='store_true')
    p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args();root=a.root
    samples=root/'orb60/build/dense/samples-midas';out=root/'orb60/build/kv260/fastdepth';source=out/'assets/fast_depth_224x224.onnx'
    frames=json.loads((samples/'samples.json').read_text())['frames']
    if len(frames)!=20:raise ValueError('Twenty real acceptance samples required')
    import torch
    from .model import FastDepth
    torch.set_num_threads(4);model=FastDepth(source);reference=Reference(source) if a.stage=='float' else None
    name=('quantized_cle' if a.equalization else 'quantized')+('_nocorr' if a.no_bias_correction else '')
    folder=out/'reference' if a.stage=='float' else out/name;folder.mkdir(parents=True,exist_ok=True)
    report={'status':'RUNNING','family':'fastdepth','stage':a.stage,'source_sha256':digest(source),'frames':[],
            'hardware_inference_verified':False,'input':'external ImageNet normalized RGB 256 -> RGB [0,1] 224 on PS',
            'equalization':a.equalization,
            'parameter_correction':not a.no_bias_correction,
            'output':'native depth 224 -> resize and reciprocal to inverse depth 256 on PS'}
    path=out/'float_gate.json' if a.stage=='float' else folder/('quantization_'+a.stage+'.json');save(path,report)
    try:
        if a.stage=='float':
            for f in frames:
                x=read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE)
                if digest(samples/(f['id']+'.input.f32'))!=f['input_sha256']:raise ValueError('Sample hash mismatch')
                native=reference.native(x);inverse=to_inverse(native)
                with torch.no_grad():converted=model(torch.from_numpy(to_native(x))).numpy()
                error=float(np.max(np.abs(native-converted)));limit=.002*max(1.,float(native.max()))
                row={'id':f['id'],'passed':error<=limit,'max_abs_error':error,'limit':limit,**evaluate(native,converted)}
                np.save(folder/(f['id']+'.reference.npy'),inverse);np.save(folder/(f['id']+'.native.npy'),native)
                report['frames'].append(row);print('FASTDEPTH_FLOAT',f['id'],flush=True)
            report['status']='FLOAT_PASS' if all(f['passed'] for f in report['frames']) else 'FAILED'
        else:
            from pytorch_nndct.apis import torch_quantizer
            from nndct_shared.utils import NndctOption
            NndctOption.nndct_equalization.value=a.equalization;NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_convert_relu6_to_relu.value=False;NndctOption.nndct_quant_off.value=False
            NndctOption.nndct_param_corr.value=not a.no_bias_correction
            if json.loads((out/'float_gate.json').read_text())['status']!='FLOAT_PASS':raise ValueError('FastDepth FP32 gate required')
            float_checks=[]
            for f in frames:
                x=read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE)
                with torch.no_grad():native=model(torch.from_numpy(to_native(x))).numpy()
                expected=np.load(out/'reference'/(f['id']+'.native.npy'));error=float(np.max(np.abs(expected-native)));limit=.002*max(1.,float(expected.max()))
                float_checks.append({'id':f['id'],'passed':error<=limit,'max_abs_error':error})
            report['toolchain_float_gate']=float_checks
            if not all(f['passed'] for f in float_checks):raise ValueError('VAI PyTorch float output differs from FastDepth reference')
            if a.stage=='test':validate_quant_config(json.loads((folder/'quant_info.json').read_text()))
            example=torch.from_numpy(to_native(read_tensor(samples/(frames[0]['id']+'.input.f32'),INPUT_SHAPE)))
            quantizer=torch_quantizer(a.stage,model,(example,),output_dir=str(folder),bitwidth=8,device=torch.device('cpu'))
            qmodel=quantizer.quant_model.eval()
            for f in frames:
                input_path=samples/(f['id']+'.input.f32')
                if digest(input_path)!=f['input_sha256']:raise ValueError('Sample hash mismatch')
                x=read_tensor(input_path,INPUT_SHAPE)
                with torch.no_grad():native=qmodel(torch.from_numpy(to_native(x))).detach().numpy()
                row={'id':f['id'],'input_sha256':f['input_sha256']}
                if a.stage=='test':
                    value=to_inverse(native);value.tofile(folder/(f['id']+'.output.f32'))
                    row.update(evaluate(np.load(out/'reference'/(f['id']+'.reference.npy')),value))
                    row['native_depth']=evaluate(np.load(out/'reference'/(f['id']+'.native.npy')),native)
                    row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98
                report['frames'].append(row);print('FASTDEPTH_'+a.stage.upper(),f['id'],flush=True)
            if a.stage=='calib':
                quantizer.export_quant_config();report['quantized_parameters']=validate_quant_config(json.loads((folder/'quant_info.json').read_text()));report['status']='CALIBRATION_PASS'
            else:
                report.update(status='QUANTIZATION_PASS' if all(f['passed'] for f in report['frames']) else 'QUANTIZATION_FAILED',
                              worst_nrmse=max(f['normalized_rmse'] for f in report['frames']),minimum_spearman=min(f['spearman'] for f in report['frames']))
                save(folder/'quantized_reference.json',{'family':'fastdepth','source_onnx':os.path.relpath(source,folder),'source_sha256':digest(source),
                     'equalization':a.equalization,
                     'parameter_correction':not a.no_bias_correction,
                     'quant_config_sha256':digest(folder/'quant_info.json'),'bias_correction_sha256':digest(folder/'bias_corr.pth') if (folder/'bias_corr.pth').exists() else None})
                quantizer.export_xmodel(output_dir=str(folder),deploy_check=False)
                report['artifacts']={p.name:digest(p) for p in folder.iterdir() if p.suffix in {'.xmodel','.pth','.json'} and p.name!='quantization_test.json'}
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(path,report);raise
    save(path,report)
    if report['status'] in {'FAILED','QUANTIZATION_FAILED'}:raise SystemExit(1)

if __name__=='__main__':main()
