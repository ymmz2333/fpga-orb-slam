"""Run only in pinned Vitis AI 2.5 PyTorch environment; no host fake quantization."""
import argparse
import json
from pathlib import Path
import platform
import os
import shutil
import time
import numpy as np
from .common import digest,load_midas,read_tensor,save,INPUT_SHAPE
from .metrics import evaluate


def main():
    p=argparse.ArgumentParser()
    for key in ['assets','samples','reference','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--mode',choices=['calib','test'],required=True)
    p.add_argument('--recipe',choices=['native-static','reluk-cle'],default='native-static');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    report={'status':'STARTED','mode':a.mode,'hardware_inference_verified':False,'frames':[]}
    prior=a.output/('quantization_'+a.mode+'.json')
    if prior.exists():
        history=a.output/'history'/str(time.time_ns());history.mkdir(parents=True)
        for name in [prior.name,'quant_info.json','bias_corr.pth']:
            if (a.output/name).exists():shutil.copyfile(a.output/name,history/name)
    save(prior,report)
    try:
        import torch
        from pytorch_nndct.apis import torch_quantizer
        from nndct_shared.utils import NndctOption
        import pytorch_nndct
        # ReLUk retains the upper bound under cross-layer equalization; plain ReLU does not.
        NndctOption.nndct_relu6_replace.value='reluk'
        NndctOption.nndct_equalization.value=a.recipe=='reluk-cle'
        NndctOption.nndct_convert_relu6_to_relu.value=False
        NndctOption.nndct_quant_off.value=False
        torch.set_num_threads(4)
        report.update(torch=torch.__version__,python=platform.python_version(),nndct=getattr(pytorch_nndct,'__version__','unknown'),
                      weight_sha256=digest(a.assets/'midas_v21_small_256.pt'))
        frames=json.loads((a.samples/'samples.json').read_text())['frames']
        if len(frames)!=20:raise ValueError('Exactly twenty frozen real samples required')
        model=load_midas(a.assets,static_padding=True)
        example=torch.from_numpy(read_tensor(a.samples/(frames[0]['id']+'.input.f32'),INPUT_SHAPE))
        report['policy']={'recipe':a.recipe,'relu6':'equivalent bounded ReLUk' if a.recipe=='reluk-cle' else 'native ReLU6 retained',
                          'equalization':a.recipe=='reluk-cle','static_same_padding':True,'quant_off':False}
        if a.mode=='calib':
            float_quantizer=torch_quantizer('calib',model,(example,),output_dir=str(a.output/'float_conversion'),bitwidth=8,device=torch.device('cpu'))
            qmodel=float_quantizer.quant_model.eval()
            NndctOption.nndct_quant_off.value=True;checks=[]
            for f in frames:
                x=read_tensor(a.samples/(f['id']+'.input.f32'),INPUT_SHAPE)
                reference=np.load(a.reference/(f['id']+'.reference.npy')).reshape(256,256)
                with torch.no_grad():converted=qmodel(torch.from_numpy(x)).detach().numpy().reshape(256,256)
                error=float(np.max(np.abs(reference-converted)));limit=.002*max(1.,float(reference.max()))
                checks.append({'id':f['id'],'max_abs_error':error,'limit':limit,'passed':error<=limit,**evaluate(reference,converted)})
            NndctOption.nndct_quant_off.value=False
            report['conversion_float_gate']=checks
            if not all(f['passed'] for f in checks):raise ValueError('Vitis AI converted float graph changed original model semantics')
            # A quant-off forward marks per-module parameters as processed in VAI 2.5.
            # Never reuse that state for actual calibration; create an independent model.
            del qmodel,float_quantizer,model
            model=load_midas(a.assets,static_padding=True)
        else:
            from .quant_config import validate_quant_config
            validate_quant_config(json.loads((a.output/'quant_info.json').read_text()))
        quantizer=torch_quantizer(a.mode,model,(example,),output_dir=str(a.output),bitwidth=8,device=torch.device('cpu'))
        qmodel=quantizer.quant_model.eval()
        for f in frames:
            path=a.samples/(f['id']+'.input.f32')
            if digest(path)!=f['input_sha256']:raise ValueError('Calibration input mismatch')
            x=read_tensor(path,INPUT_SHAPE)
            with torch.no_grad():value=qmodel(torch.from_numpy(x)).detach().cpu().numpy().reshape(256,256)
            row={'id':f['id'],'input_sha256':digest(path)}
            if a.mode=='test':
                row.update(evaluate(np.load(a.reference/(f['id']+'.reference.npy')),value))
                row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98
                value.astype('<f4').tofile(a.output/(f['id']+'.output.f32'))
            report['frames'].append(row);print('INT8_'+a.mode.upper(),f['id'],flush=True)
        if a.mode=='calib':
            quantizer.export_quant_config()
            from .quant_config import validate_quant_config
            report['quantized_parameters']=validate_quant_config(json.loads((a.output/'quant_info.json').read_text()))
            report['status']='CALIBRATION_PASS'
        else:
            report['status']='QUANTIZATION_PASS' if all(f['passed'] for f in report['frames']) else 'QUANTIZATION_FAILED'
            report['numerical_status']=report['status']
            report['worst_nrmse']=max(f['normalized_rmse'] for f in report['frames'])
            report['minimum_spearman']=min(f['spearman'] for f in report['frames'])
            # Export real artifacts even if the numerical gate fails; never label them accepted.
            save(a.output/'quantized_reference.json',{'backend':'quantized-reference','assets':os.path.relpath(a.assets,a.output),
                                                   'weight_sha256':report['weight_sha256'],'quant_config_sha256':digest(a.output/'quant_info.json'),
                                                   'bias_correction_sha256':digest(a.output/'bias_corr.pth') if (a.output/'bias_corr.pth').exists() else None,
                                                   'policy':report['policy']})
            quantizer.export_xmodel(output_dir=str(a.output),deploy_check=False)
            try:
                quantizer.export_traced_torch_script(output_dir=str(a.output));report['torchscript_export']='EXPORTED'
            except Exception as e:report['torchscript_export']='FAILED_OPTIONAL';report['torchscript_error']=repr(e)
            report['artifacts']={str(p.relative_to(a.output)):digest(p) for p in a.output.glob('*') if p.suffix in {'.pt','.pth','.xmodel','.json'} and p.name!='quantization_test.json'}
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(a.output/('quantization_'+a.mode+'.json'),report);raise
    save(a.output/('quantization_'+a.mode+'.json'),report)
    if report['status']=='QUANTIZATION_FAILED':raise SystemExit(1)

if __name__=='__main__':main()
