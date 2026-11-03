"""End-to-end INT8 QAT distillation, with separate training/selection/frozen-gate frames."""
import argparse
import json
import os
import time
from pathlib import Path
import numpy as np
import torch
from pytorch_nndct import QatProcessor
from nndct_shared.utils import NndctOption
from ..common import load_midas,read_tensor,digest,save,INPUT_SHAPE,checked_id
from ..metrics import evaluate
from .qat_model import prepare


def main():
    p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=4);p.add_argument('--resume',action='store_true')
    p.add_argument('--run-name',default='qat-e2e');p.add_argument('--initial-checkpoint',type=Path)
    p.add_argument('--weights-from',type=Path)
    p.add_argument('--weight-lr',type=float,default=1e-5);p.add_argument('--quant-lr',type=float,default=1e-3);a=p.parse_args()
    root=Path('/workspace/orb60/build');out=root/'kv260/midas_refine'/checked_id(a.run_name);out.mkdir(parents=True,exist_ok=True);os.chdir(out)
    torch.set_num_threads(2);torch.manual_seed(42);np.random.seed(42)
    NndctOption.nndct_equalization.value=False;NndctOption.nndct_convert_relu6_to_relu.value=False
    NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_param_corr.value=False
    samples=root/'dense/samples-midas';frozen=json.loads((samples/'samples.json').read_text())['frames'];reserved={f['source_frame_index'] for f in frozen}
    replay=root/'kv260/replay_inputs';candidates=[f for m in json.loads((replay/'keyframes.json').read_text())['maps'] for f in m['frames'] if f['selected'] and f['source_frame_index'] not in reserved]
    select=candidates[::7];select_names={f['name'] for f in select};train=[f for f in candidates if f['name'] not in select_names]
    report={'status':'RUNNING','method':'end-to-end QAT distillation','epochs':[],'training':[f['name'] for f in train],
            'weight_learning_rate':a.weight_lr,'quantizer_learning_rate':a.quant_lr,
            'internal_validation':[f['name'] for f in select],'frozen_gate_source_indices':sorted(reserved),'hardware_verified':False,
            'original_weight_sha256':digest(root/'dense/assets/midas_v21_small_256.pt'),'code_sha256':digest(__file__)}
    report.update(samples_manifest_sha256=digest(samples/'samples.json'),replay_manifest_sha256=digest(replay/'keyframes.json'),
                  qat_adapter_sha256=digest(Path(__file__).with_name('qat_model.py')),torch_version=torch.__version__)
    (out/'source_snapshot.py').write_bytes(Path(__file__).read_bytes())
    save(out/'training.json',report);tick=time.monotonic()
    try:
        teacher=load_midas(root/'dense/assets',static_padding=True)
        tensors={};targets={}
        with torch.no_grad():
            for f in candidates:
                path=replay/'inputs'/(f['name']+'.input.f32')
                if digest(path)!=f['input_sha256']:raise ValueError('Training provenance mismatch')
                x=torch.from_numpy(read_tensor(path,INPUT_SHAPE));y=teacher(x).detach()
                tensors[f['name']]=x;targets[f['name']]=y
        example=tensors[train[0]['name']]
        model=prepare(teacher)
        # No weight/resize semantics are changed by the QAT module adaptation.
        checks=[]
        with torch.no_grad():
            for f in frozen:
                x=torch.from_numpy(read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE))
                original=np.load(root/'dense/midas-small-fp16'/(f['id']+'.reference.npy'))
                value=model(x).numpy();error=float(np.max(np.abs(value-original)));limit=.002*max(1.,float(original.max()))
                checks.append({'id':f['id'],'max_abs_error':error,'limit':limit,'passed':error<=limit})
        report['float_rewrite_gate']=checks
        if not all(c['passed'] for c in checks):raise ValueError('QAT graph adaptation changed float semantics')
        model.train();processor=QatProcessor(model,(example,),bitwidth=8,device=torch.device('cpu'))
        student=processor.trainable_model(allow_reused_module=True);student.train();student.freeze_bn_stats()
        optimizer=torch.optim.Adam([{'params':student.non_quantizer_parameters(),'lr':a.weight_lr},
                                    {'params':student.quantizer_parameters(),'lr':a.quant_lr}])
        best=float('inf');start=0
        if a.weights_from:
            student.load_state_dict(torch.load(a.weights_from,map_location='cpu'))
            report['initial_weights_sha256']=digest(a.weights_from)
            torch.save(student.state_dict(),out/'best.pth')
            student.eval();initial=[]
            with torch.no_grad():
                for f in select:
                    name=f['name'];initial.append(evaluate(targets[name].numpy(),student(tensors[name]).numpy())['normalized_rmse'])
            best=float(np.mean(initial));report['initial_selection_mean_nrmse']=best
        if a.resume or a.initial_checkpoint:
            path=a.initial_checkpoint or out/'latest.pth'
            state=torch.load(path,map_location='cpu');student.load_state_dict(state['model']);optimizer.load_state_dict(state['optimizer'])
            start=state['epoch']+1;best=state['best']
            for group,lr in zip(optimizer.param_groups,[a.weight_lr,a.quant_lr]):group['lr']=lr
            report['resume_checkpoint_sha256']=digest(path)
            if a.initial_checkpoint:
                import shutil
                shutil.copyfile(path.parent/'best.pth',out/'best.pth')
        for epoch in range(start,a.epochs):
            student.train();student.freeze_bn_stats();losses=[]
            for step,idx in enumerate(np.random.RandomState(42+epoch).permutation(len(train))):
                name=train[idx]['name'];x=tensors[name];target=targets[name];span=torch.quantile(target,.95)-torch.quantile(target,.05)
                optimizer.zero_grad();prediction=student(x);loss=((prediction-target)/span.clamp(min=1e-6)).square().mean()
                if not torch.isfinite(loss):raise ValueError('Nonfinite training loss')
                loss.backward();torch.nn.utils.clip_grad_norm_(student.parameters(),1.);optimizer.step();losses.append(float(loss.detach()))
                if step%10==0:print('QAT_STEP',epoch,step,'loss',losses[-1],flush=True)
            student.eval();errors=[]
            with torch.no_grad():
                for f in select:
                    name=f['name'];pred=student(tensors[name]);errors.append(evaluate(targets[name].numpy(),pred.numpy()))
            score=float(np.mean([r['normalized_rmse'] for r in errors]));record={'epoch':epoch,'train_mse':float(np.mean(losses)),
                'selection_mean_nrmse':score,'selection_worst_nrmse':max(r['normalized_rmse'] for r in errors)}
            if score<best:
                best=score;torch.save(student.state_dict(),out/'best.pth')
            torch.save({'epoch':epoch,'model':student.state_dict(),'optimizer':optimizer.state_dict(),'best':best},out/'latest.pth')
            report['epochs'].append(record);save(out/'training.json',report);print('QAT_EPOCH',record,flush=True)
        student.load_state_dict(torch.load(out/'best.pth',map_location='cpu'));student.eval();student.freeze_quant()
        report.update(status='QAT_TRAINED_DEPLOY_CONVERSION_PENDING',best_weight_sha256=digest(out/'best.pth'))
        save(out/'training.json',report)
        deploy=out/'deploy';deploy.mkdir(exist_ok=True)
        model=processor.to_deployable(student,str(deploy));model.eval();rows=[]
        for f in frozen:
            x=torch.from_numpy(read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE))
            with torch.no_grad():value=model(x).numpy().reshape(256,256)
            row={'id':f['id'],**evaluate(np.load(root/'dense/midas-small-fp16'/(f['id']+'.reference.npy')),value)}
            row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98;rows.append(row)
            value.astype('<f4').tofile(out/(f['id']+'.output.f32'));print('QAT_FROZEN_GATE',row,flush=True)
        report.update(status='QUANTIZATION_PASS' if all(r['passed'] for r in rows) else 'QUANTIZATION_FAILED',frames=rows,
                      passed=sum(r['passed'] for r in rows),worst_nrmse=max(r['normalized_rmse'] for r in rows),minimum_spearman=min(r['spearman'] for r in rows))
        save(out/'test.json',report)
        if report['status']=='QUANTIZATION_PASS':processor.export_xmodel(str(deploy))
    except Exception as e:
        report.update(status='FAILED',error=repr(e),elapsed_seconds=time.monotonic()-tick);save(out/'training.json',report);raise
    report['elapsed_seconds']=time.monotonic()-tick;save(out/'training.json',report)

if __name__=='__main__':main()
