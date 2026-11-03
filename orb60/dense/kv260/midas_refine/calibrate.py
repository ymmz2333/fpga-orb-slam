"""Calibrate on saved real keyframes excluding all twenty frozen validation frame indices."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from pytorch_nndct.apis import torch_quantizer
from nndct_shared.utils import NndctOption
from ..common import load_midas,read_tensor,save,digest,INPUT_SHAPE
from ..metrics import evaluate


def main():
    p=argparse.ArgumentParser();p.add_argument('--statistic',choices=['modal','min'],required=True);p.add_argument('--mode',choices=['calib','test'],required=True);a=p.parse_args()
    root=Path('orb60/build');out=root/'kv260/midas_refine'/('realkeyframes-'+a.statistic);out.mkdir(parents=True,exist_ok=True)
    frozen=root/'dense/samples-midas';validation=json.loads((frozen/'samples.json').read_text())['frames']
    held={f['source_frame_index'] for f in validation}
    replay=root/'kv260/replay_inputs';manifest=json.loads((replay/'keyframes.json').read_text())
    calibration=[f for m in manifest['maps'] for f in m['frames'] if f['selected'] and f['source_frame_index'] not in held]
    torch.set_num_threads(2)
    NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_equalization.value=True
    NndctOption.nndct_convert_relu6_to_relu.value=False;NndctOption.nndct_quant_off.value=False
    model=load_midas(root/'dense/assets',static_padding=True)
    example=read_tensor(replay/'inputs'/(calibration[0]['name']+'.input.f32'),INPUT_SHAPE)
    q=torch_quantizer(a.mode,model,(torch.from_numpy(example),),output_dir=str(out),bitwidth=8,device=torch.device('cpu'))
    report={'status':'RUNNING','mode':a.mode,'statistic':a.statistic,'calibration_frames':len(calibration),
            'excluded_validation_source_indices':sorted(held),'weight_sha256':digest(root/'dense/assets/midas_v21_small_256.pt'),
            'code_sha256':digest(__file__),'preparation_sha256':digest(replay/'keyframes.json'),
            'calibration_separation':'different source frame indices, same real video; not an independent-scene test',
            'hardware_verified':False,'frames':[]}
    save(out/(a.mode+'.json'),report)
    try:
        if a.mode=='calib':
            for f in calibration:
                path=replay/'inputs'/(f['name']+'.input.f32')
                if digest(path)!=f['input_sha256']:raise ValueError('Replay input hash mismatch')
                with torch.no_grad():q.quant_model(torch.from_numpy(read_tensor(path,INPUT_SHAPE)))
                report['frames'].append({'id':f['name'],'source_frame_index':f['source_frame_index'],'input_sha256':digest(path)})
                print('CALIBRATE_REAL',a.statistic,f['name'],flush=True)
            histories={group:{name:[int(v) for v in values] for name,values in entries.items()}
                       for group,entries in q.processor.quantizer.config_history.items()}
            save(out/'fixpoint_history.json',histories)
            if a.statistic=='min':
                for group,entries in histories.items():
                    for name,values in entries.items():
                        if values:
                            prior=q.processor.quantizer.get_quant_config(name,real_value=False,tensor_type=group)
                            q.processor.quantizer.set_quant_config(name,[prior[0],int(min(values))],tensor_type=group)
            q.export_quant_config();report['status']='CALIBRATION_COMPLETE'
        else:
            # Check semantics of this exact transformed graph on a separate fresh quant-off instance.
            # Actual INT8 evaluation does not do any output scale/shift alignment.
            for f in validation:
                path=frozen/(f['id']+'.input.f32')
                if digest(path)!=f['input_sha256']:raise ValueError('Validation input mismatch')
                with torch.no_grad():value=q.quant_model(torch.from_numpy(read_tensor(path,INPUT_SHAPE))).numpy().reshape(256,256)
                reference=np.load(root/'dense/midas-small-fp16'/(f['id']+'.reference.npy'))
                row={'id':f['id'],**evaluate(reference,value)};row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98
                report['frames'].append(row);value.astype('<f4').tofile(out/(f['id']+'.output.f32'));print('REAL_CALIB_TEST',row,flush=True)
            report.update(status='QUANTIZATION_PASS' if all(f['passed'] for f in report['frames']) else 'QUANTIZATION_FAILED',
                          passed=sum(f['passed'] for f in report['frames']),worst_nrmse=max(f['normalized_rmse'] for f in report['frames']),
                          minimum_spearman=min(f['spearman'] for f in report['frames']))
            if report['status']=='QUANTIZATION_PASS':
                q.export_xmodel(output_dir=str(out),deploy_check=False)
                report['xmodels']={f.name:digest(f) for f in out.glob('*.xmodel')}
    except Exception as e:
        report.update(status='FAILED',error=repr(e));save(out/(a.mode+'.json'),report);raise
    save(out/(a.mode+'.json'),report)

if __name__=='__main__':main()
