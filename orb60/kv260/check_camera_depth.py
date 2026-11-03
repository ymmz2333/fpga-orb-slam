"""Actual DPU inference on a preserved, CRC-checked USB camera sample.

This does not supply poses or create a world map from a stationary camera.
"""
import argparse
import csv
import json
from pathlib import Path
import time
import zlib
import cv2
import numpy as np
from .camera_input import to_bgr
from .dense_service import DpuDepth
from .run_network_system import digest,save


def run(config,capture_run,output,index=90):
    config=json.loads(Path(config).read_text());source=Path(capture_run);output=Path(output)
    receipt=json.loads((source/'RESULT.json').read_text())
    if receipt['input']!='actual_KV260_USB_uncompressed_camera' or receipt['status'] not in (
        'ACTUAL_USB_CAMERA_CAPTURE_COMPONENT_PASS','ACTUAL_USB_CAMERA_PHYSICAL_ORB_COMPONENT_PASS'):
        raise ValueError('Actual verified USB camera capture required')
    with (source/'frames.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    row=rows[index];stem=source/('sample_%04d'%index)
    raw=stem.with_suffix('.yuyv').read_bytes();gray=stem.with_suffix('.gray8').read_bytes()
    if zlib.crc32(raw)!=int(row['packed_crc']) or zlib.crc32(gray)!=int(row['gray_crc']):
        raise ValueError('Camera sample CRC differs from capture journal')
    packed=np.frombuffer(raw,np.uint8).reshape(720,960,2)
    bgr=to_bgr(packed,receipt['negotiated_profile'])
    if not np.array_equal(packed[:,:,0],np.frombuffer(gray,np.uint8).reshape(720,960)) or not np.array_equal(bgr,cv2.imread(str(stem.with_suffix('.png')))):
        raise ValueError('Sample color/luma identity mismatch')
    preflight=json.loads(Path(config['preflight']).read_text())
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if preflight.get('status')!='PROFILE_MATCH' or preflight.get('driver')!='vivado' or preflight.get('boot_id')!=boot:
        raise ValueError('Actual current-boot DPU preflight required')
    output.mkdir(parents=True,exist_ok=False);engine=None
    report=dict(status='RUNNING',scope=__doc__,backend='dpu',boot_id=boot,
                source_frame_id=index,capture_sequence=int(row['capture_sequence']),timestamp_ns=int(row['timestamp_ns']),
                source_png_sha256=digest(stem.with_suffix('.png')),gray_crc=int(row['gray_crc']),
                model_sha256=digest(config['model']),preflight_sha256=digest(config['preflight']))
    try:
        engine=DpuDepth(config,output);began=time.monotonic();prediction=engine.infer('camera_sample_%04d'%index,bgr)
        elapsed=time.monotonic()-began;engine.close();engine=None
        worker=json.loads((output/'depth/worker.json').read_text())
        if worker['backend']!='dpu' or not worker['hardware_inference_verified'] or worker['hardware_driver']!='vivado' or len(worker['frames'])!=1 or worker['frames'][0]['reused']:
            raise ValueError('Actual non-reused DPU camera inference not verified')
        if prediction.shape!=(256,256) or not np.isfinite(prediction).all() or float(prediction.std())<=1e-5:
            raise ValueError('Invalid/constant camera relative inverse-depth output')
        lo,hi=np.percentile(prediction,[2,98]);view=np.clip((prediction-lo)/max(hi-lo,1e-6)*255,0,255).astype(np.uint8)
        if not cv2.imwrite(str(output/'relative_inverse_depth.png'),cv2.applyColorMap(view,cv2.COLORMAP_TURBO)):
            raise RuntimeError('Depth preview write failed')
        report.update(status='ACTUAL_DPU_USB_CAMERA_SAMPLE_INFERENCE_PASS',hardware_inference_verified=True,
                      worker_status=worker['status'],seconds=elapsed,output_shape=[256,256],
                      output_min=float(prediction.min()),output_max=float(prediction.max()),output_std=float(prediction.std()),
                      point_cloud_generated=False,numerical_gate='Selected retained model binding; new camera scene has no depth ground truth')
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        try:
            if engine:engine.close()
        finally:save(output/'RESULT.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('config','capture-run','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--index',type=int,default=90)
    run(**vars(p.parse_args()))
