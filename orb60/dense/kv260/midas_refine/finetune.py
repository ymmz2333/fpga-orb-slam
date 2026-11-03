"""Vendor AdaQuant weight adaptation, with twenty held-out frozen validation frames."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import torch
from pytorch_nndct.apis import torch_quantizer
from nndct_shared.utils import NndctOption
from ..common import load_midas,read_tensor,save,digest,INPUT_SHAPE
from ..metrics import evaluate


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['fit','test'],required=True);p.add_argument('--training-frames',type=int,default=4);a=p.parse_args()
    root=Path('orb60/build');out=root/'kv260/midas_refine'/('adaquant-%d'%a.training_frames);out.mkdir(parents=True,exist_ok=True)
    samples=root/'dense/samples-midas';frozen=json.loads((samples/'samples.json').read_text())['frames']
    reserved={f['source_frame_index'] for f in frozen};replay=root/'kv260/replay_inputs'
    candidates=[f for m in json.loads((replay/'keyframes.json').read_text())['maps'] for f in m['frames'] if f['selected'] and f['source_frame_index'] not in reserved]
    selected=[candidates[i] for i in np.linspace(0,len(candidates)-1,a.training_frames).astype(int)]
    if len({f['name'] for f in selected})!=a.training_frames:raise ValueError('Invalid training count')
    torch.set_num_threads(2);torch.manual_seed(42);np.random.seed(42)
    NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_equalization.value=True
    NndctOption.nndct_convert_relu6_to_relu.value=False;NndctOption.nndct_param_corr.value=False
    NndctOption.nndct_quant_off.value=False
    report={'mode':a.mode,'status':'RUNNING','method':'Vitis AI 2.5 AdaQuant layer-wise weight adaptation, not full end-to-end QAT',
            'training_frames':[{'id':f['name'],'source_frame_index':f['source_frame_index'],'input_sha256':f['input_sha256']} for f in selected],
            'reserved_source_indices':sorted(reserved),'original_weight_sha256':digest(root/'dense/assets/midas_v21_small_256.pt'),
            'code_sha256':digest(__file__),'hardware_verified':False,'dpu_deployable':False,'frames':[]}
    save(out/(a.mode+'.json'),report);started=time.monotonic()
    try:
        model=load_midas(root/'dense/assets',static_padding=True)
        example=read_tensor(replay/'inputs'/(selected[0]['name']+'.input.f32'),INPUT_SHAPE)
        q=torch_quantizer('calib' if a.mode=='fit' else 'test',model,(torch.from_numpy(example),),output_dir=str(out),bitwidth=8,device=torch.device('cpu'))
        def execute(frames):
            with torch.no_grad():
                for f in frames:
                    path=replay/'inputs'/(f['name']+'.input.f32')
                    if digest(path)!=f['input_sha256']:raise ValueError('Training input hash mismatch')
                    q.quant_model(torch.from_numpy(read_tensor(path,INPUT_SHAPE)))
        if a.mode=='fit':
            before={n:p.detach().clone() for n,p in q.quant_model.named_parameters()}
            print('ADAQUANT_START',len(selected),flush=True)
            q.fast_finetune(execute,(selected,))
            changed=[n for n,p in q.quant_model.named_parameters() if not torch.equal(p.detach(),before[n])]
            report['changed_parameter_tensors']=changed
            if not changed:raise RuntimeError('Vendor fine-tuning changed no weights')
            del before
            # Recalibrate adapted weights on the larger, held-out-safe real input set.
            print('ADAQUANT_RECALIBRATE',len(candidates),flush=True);execute(candidates)
            q.export_quant_config()
            files={f.name:digest(f) for f in out.glob('*.pth')}
            if not files:raise RuntimeError('No real adapted parameter artifact was exported')
            report.update(status='ADAPTED_WEIGHTS_SAVED_VALIDATION_PENDING',parameters=files)
        else:
            q.processor.quantizer.load_param()
            for f in frozen:
                path=samples/(f['id']+'.input.f32')
                if digest(path)!=f['input_sha256']:raise ValueError('Validation hash mismatch')
                with torch.no_grad():value=q.quant_model(torch.from_numpy(read_tensor(path,INPUT_SHAPE))).numpy().reshape(256,256)
                row={'id':f['id'],**evaluate(np.load(root/'dense/midas-small-fp16'/(f['id']+'.reference.npy')),value)}
                row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98;report['frames'].append(row)
                value.astype('<f4').tofile(out/(f['id']+'.output.f32'));print('ADAQUANT_VALIDATE',row,flush=True)
            report.update(status='QUANTIZATION_PASS' if all(f['passed'] for f in report['frames']) else 'QUANTIZATION_FAILED',
                          passed=sum(f['passed'] for f in report['frames']),worst_nrmse=max(f['normalized_rmse'] for f in report['frames']),minimum_spearman=min(f['spearman'] for f in report['frames']))
            if report['status']=='QUANTIZATION_PASS':q.export_xmodel(output_dir=str(out),deploy_check=False)
    except Exception as e:
        report.update(status='FAILED',error=repr(e),elapsed_seconds=time.monotonic()-started);save(out/(a.mode+'.json'),report);raise
    report['elapsed_seconds']=time.monotonic()-started;save(out/(a.mode+'.json'),report)

if __name__=='__main__':main()
