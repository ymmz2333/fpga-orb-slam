"""Benchmark UI drawing on one actual PL telemetry frame, never whole-system FPS."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import time
import cv2
import numpy as np
from .feature_overlay import draw_batch
from .dense_fusion import save
from orb60.viewer.protocol import Snapshot


def reference(image,features):
    for x,y,octave,mapped in features:
        cv2.circle(image,(round(x),round(y)),3,(135,230,60) if mapped else (40,188,245),1,cv2.LINE_AA)


def run(snapshot,output):
    snapshot,output=Path(snapshot),Path(output);output.mkdir(parents=True,exist_ok=False)
    record=Snapshot.decode(snapshot.read_bytes());features=record.meta['features']
    if record.meta['source']!='fpga' or record.meta['cpu_orb_calls']!=0 or not features:raise ValueError('Actual PL telemetry frame required')
    source=cv2.imdecode(np.frombuffer(record.jpeg,np.uint8),cv2.IMREAD_COLOR)
    source=cv2.cvtColor(cv2.cvtColor(source,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
    identity=hashlib.sha256(json.dumps(features).encode()).hexdigest();times={};images={}
    for name,draw in (('reference',reference),('batch',draw_batch)):
        samples=[]
        for _ in range(30):
            image=source.copy();began=time.perf_counter_ns();draw(image,features);samples.append((time.perf_counter_ns()-began)*1e-6)
        images[name]=image;times[name]=samples
        if not cv2.imwrite(str(output/(name+'.png')),image):raise ValueError('Cannot save actual marker preview')
    if hashlib.sha256(json.dumps(features).encode()).hexdigest()!=identity:raise ValueError('Feature identity modified by drawing')
    if any(np.median(v)<=0 for v in times.values()):raise ValueError('Clock resolution is insufficient for a drawing benchmark')
    report={'status':'UI_RENDER_MICROBENCHMARK_COMPLETE','scope':'PS drawing only, no whole-system FPS claim',
            'machine':platform.machine(),
            'source_frame':record.meta['frame_index'],'features':len(features),'features_sha256':identity,
            'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),'milliseconds':times,
            'median_ms':{k:float(np.median(v)) for k,v in times.items()},
            'speedup':float(np.median(times['reference'])/np.median(times['batch'])),
            'pixels_different':int(np.count_nonzero(np.any(images['reference']!=images['batch'],axis=2))),
            'geometry_changed':False,'visual_change':'None: original circle radius, AA, colors and paint order retained',
            'pixels_byte_identical':images['reference'].tobytes()==images['batch'].tobytes()}
    if not report['pixels_byte_identical']:raise ValueError('Batch markers differ from original pixels')
    save(output/'RESULT.json',report);print(json.dumps({k:v for k,v in report.items() if k!='milliseconds'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
