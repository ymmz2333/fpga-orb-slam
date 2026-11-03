"""Reproduce the selected QAT reference, then replay saved keyframes and sampled real video."""
import json
from pathlib import Path
import time
import numpy as np
import cv2
import torch
from pytorch_nndct import QatProcessor
from nndct_shared.utils import NndctOption
from ..common import load_midas,read_tensor,write_tensor,save,digest,preprocess,INPUT_SHAPE
from ..metrics import evaluate
from .. import worker
from .qat_model import prepare


class QatReference:
    def __init__(self,root,out):
        torch.set_num_threads(2);torch.manual_seed(42);np.random.seed(42)
        NndctOption.nndct_equalization.value=False;NndctOption.nndct_convert_relu6_to_relu.value=False
        NndctOption.nndct_relu6_replace.value='reluk';NndctOption.nndct_param_corr.value=False;NndctOption.nndct_quant_off.value=False
        checkpoint=root/'kv260/midas_refine/qat-e2e/best.pth'
        chosen=json.loads((root/'kv260/midas_refine/BEST_CANDIDATE.json').read_text())
        if digest(checkpoint)!=chosen['weights_sha256']:raise ValueError('Selected QAT weight identity mismatch')
        spec={'backend':'quantized-reference','checkpoint_sha256':digest(checkpoint),
              'adapter_sha256':digest(Path(__file__).with_name('qat_model.py')),'numerical_gate':'FAILED_DIAGNOSTIC_USE_ONLY',
              'original_weight_sha256':digest(root/'dense/assets/midas_v21_small_256.pt')}
        save(out/'model_identity.json',spec)
        model=load_midas(root/'dense/assets',static_padding=True)
        example=torch.from_numpy(read_tensor(root/'kv260/replay_inputs/inputs/m0_k7.input.f32',INPUT_SHAPE))
        with torch.no_grad():model(example)
        model=prepare(model);model.train()
        self.processor=QatProcessor(model,(example,),bitwidth=8,device=torch.device('cpu'))
        student=self.processor.trainable_model(allow_reused_module=True)
        student.load_state_dict(torch.load(checkpoint,map_location='cpu'));student.eval();student.freeze_quant()
        runtime=out/'runtime';runtime.mkdir(exist_ok=True)
        self.model=self.processor.to_deployable(student,str(runtime)).eval()
        samples=root/'dense/samples-midas';frames=json.loads((samples/'samples.json').read_text())['frames'];checks=[]
        for f in frames:
            value=self(read_tensor(samples/(f['id']+'.input.f32'),INPUT_SHAPE))
            saved=read_tensor(root/'kv260/midas_refine/qat-e2e'/(f['id']+'.output.f32'),(256,256))
            checks.append({'id':f['id'],'byte_exact':bool(np.array_equal(value,saved)),'maximum_difference':float(np.max(np.abs(value-saved)))})
        save(out/'reproduction.json',{'status':'PASS' if all(c['byte_exact'] for c in checks) else 'FAILED','checks':checks})
        if not all(c['byte_exact'] for c in checks):raise ValueError('Replay engine differs from the selected twenty-frame QAT result')

    def __call__(self,x):
        with torch.no_grad():return self.model(torch.from_numpy(x)).detach().numpy().reshape(256,256)


def main():
    root=Path('/workspace/orb60/build');out=root/'kv260/midas_refine/video_test';out.mkdir(parents=True,exist_ok=True)
    # QAT writes temporary graph files relative to cwd; keep them in this experiment.
    import os
    os.chdir(out)
    status={'status':'RUNNING','backend':'quantized-reference','hardware_verified':False,'source':'real recorded video and saved keyframes'}
    save(out/'status.json',status)
    try:
        engine=QatReference(root,out)
        # Process-local injection preserves the shared worker and RK production entry points.
        worker.QuantizedReference=lambda model:engine
        inp=root/'kv260/replay_inputs/inputs'
        worker.run(out/'model_identity.json',inp,inp/'names.txt',out/'keyframe_depth','quantized-reference')
        video=Path('/workspace/recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4')
        expected=json.loads((root/'dense/samples-midas/samples.json').read_text())['video_sha256']
        if digest(video)!=expected:raise ValueError('Original video hash mismatch')
        for name in ['rgb','float_depth','qat_depth']:(out/name).mkdir(exist_ok=True)
        teacher=load_midas(root/'dense/assets',static_padding=True)
        cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS);rows=[];decoded=0
        try:
            while True:
                ok,bgr=cap.read()
                if not ok:break
                index=decoded;decoded+=1
                if index%10:continue
                name='v%05d'%index;x=preprocess(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
                with torch.no_grad():reference=teacher(torch.from_numpy(x)).numpy().reshape(256,256)
                tick=time.monotonic();value=engine(x);elapsed=time.monotonic()-tick
                write_tensor(out/'float_depth'/(name+'.f32'),reference);write_tensor(out/'qat_depth'/(name+'.f32'),value)
                if not cv2.imwrite(str(out/'rgb'/(name+'.png')),bgr):raise IOError('Failed to save real RGB frame')
                row={'id':name,'source_frame_index':index,'source_seconds':index/fps,
                     'rgb_sha256':digest(out/'rgb'/(name+'.png')),'qat_seconds':elapsed,**evaluate(reference,value)}
                rows.append(row);print('VIDEO_DEPTH',index,'nrmse',row['normalized_rmse'],flush=True)
        finally:cap.release()
        status.update(status='VIDEO_DEPTH_COMPLETE',video_sha256=expected,source_fps=fps,decoded_frames=decoded,
                      sample_stride=10,samples=rows,playback_fps=fps/10,
                      note='Sampled real video at original temporal spacing; processing speed is not board FPS or real-time performance')
        save(out/'status.json',status)
    except Exception as e:
        status.update(status='FAILED',error=repr(e));save(out/'status.json',status);raise

if __name__=='__main__':main()
