"""Explicit MiDaS on KV260 PS CPU; this backend never creates a DPU runner."""
import argparse
import json
import os
from pathlib import Path
import resource
import time
import numpy as np
from orb60.dense.kv260.common import INPUT_SHAPE, OUTPUT_SHAPE, digest, read_tensor, write_tensor, save


class CpuDepth:
    def __init__(self, config, folder=None):
        import onnxruntime as ort
        self.model = Path(config['model'])
        self.model_sha256 = digest(self.model)
        if self.model_sha256 != config['model_sha256']:
            raise ValueError('PS CPU model checksum mismatch')
        threads = int(config.get('threads',2))
        if not 1 <= threads <= 4:raise ValueError('PS MiDaS requires 1..4 threads')
        if config.get('cpu_affinity') is not None:
            requested = set(config['cpu_affinity'])
            if not requested or not requested.issubset(os.sched_getaffinity(0)):
                raise ValueError('Invalid depth CPU affinity')
            os.sched_setaffinity(0,requested)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        options.add_session_config_entry('session.inter_op.allow_spinning','0')
        self.session = ort.InferenceSession(str(self.model),options,providers=['CPUExecutionProvider'])
        inputs,outputs = self.session.get_inputs(),self.session.get_outputs()
        if len(inputs)!=1 or inputs[0].shape!=list(INPUT_SHAPE) or inputs[0].type!='tensor(float)':
            raise ValueError('PS model input must be float32 NCHW 1x3x256x256')
        if len(outputs)!=1 or tuple(outputs[0].shape) not in ((1,256,256),(256,256),(1,1,256,256)):
            raise ValueError('PS model output must contain one 256x256 inverse-depth map')
        self.input_name = inputs[0].name
        self.providers = self.session.get_providers()
        if self.providers != ['CPUExecutionProvider']:raise ValueError('Unexpected depth provider')
        self.frames = []
        self.folder = Path(folder) if folder else None
        self.runtime = ort.__version__

    def tensor(self, x):
        if x.shape!=INPUT_SHAPE or x.dtype!=np.float32 or not np.isfinite(x).all():
            raise ValueError('Invalid PS depth input')
        start, cpu = time.perf_counter(),time.process_time()
        value = self.session.run(None,{self.input_name:x})[0].reshape(OUTPUT_SHAPE)
        elapsed = time.perf_counter()-start
        if value.dtype!=np.float32 or not np.isfinite(value).all():raise ValueError('Invalid PS inverse depth')
        self.frames.append(dict(seconds=elapsed,cpu_seconds=time.process_time()-cpu))
        return value

    def infer(self, name, bgr):
        import cv2
        from orb60.dense.kv260.common import preprocess
        value = self.tensor(preprocess(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)))
        self.frames[-1]['id'] = name
        if self.folder:save(self.folder/'ps_depth.json',self.report())
        return value

    def report(self):
        return dict(backend='kv260_ps_cpu',provider=self.providers,runtime=self.runtime,
                    model_sha256=self.model_sha256,hardware_dpu_inference=False,
                    rss_peak_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,frames=self.frames)

    def close(self):
        if self.folder:save(self.folder/'ps_depth.json',self.report())


def benchmark(model, inputs, references, output, threads):
    output = Path(output);output.mkdir(parents=True,exist_ok=False)
    engine = CpuDepth(dict(model=str(model),model_sha256=digest(model),threads=threads))
    names = (Path(inputs)/'names.txt').read_text().splitlines()
    comparisons = []
    for name in names:
        x = read_tensor(Path(inputs)/(name+'.input.f32'),INPUT_SHAPE)
        value = engine.tensor(x)
        write_tensor(output/(name+'.output.f32'),value)
        reference = np.load(Path(references)/(name+'.reference.npy'),allow_pickle=False).reshape(OUTPUT_SHAPE)
        scale = float(np.percentile(reference,95)-np.percentile(reference,5))
        nrmse = float(np.sqrt(np.mean((value.astype(np.float64)-reference)**2))/scale)
        maximum = float(np.max(np.abs(value-reference)))
        comparisons.append(dict(id=name,normalized_rmse=nrmse,max_abs=maximum,passed=nrmse<=.0001,
                                input_sha256=digest(Path(inputs)/(name+'.input.f32')),
                                output_sha256=digest(output/(name+'.output.f32'))))
        print('KV260_PS_MIDAS',name,round(engine.frames[-1]['seconds'],3),'s',flush=True)
    if len(comparisons)!=20:raise ValueError('Expected all 20 retained numerical samples')
    # Separate warm steady-state repeats from the 20 distinct numerical inputs.
    x = read_tensor(Path(inputs)/(names[-1]+'.input.f32'),INPUT_SHAPE)
    repeats=[]
    for _ in range(5):
        engine.tensor(x);repeats.append(engine.frames[-1]['seconds'])
    result={**engine.report(), 'threads':threads,'comparisons':comparisons,
            'warm_repeat_seconds':repeats,'warm_median_seconds':float(np.median(repeats)),
            'status':'PS_CPU_MIDAS_20_FRAME_PASS' if all(c['passed'] for c in comparisons) else 'FAILED'}
    save(output/'benchmark.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('model','inputs','references','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--threads',type=int,default=2)
    args=parser.parse_args();result=benchmark(**vars(args))
    print(json.dumps({k:v for k,v in result.items() if k not in ('frames','comparisons')}))
    raise SystemExit(result['status']!='PS_CPU_MIDAS_20_FRAME_PASS')
