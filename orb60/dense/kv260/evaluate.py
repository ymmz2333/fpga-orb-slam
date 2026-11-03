"""Numerical and point-cloud comparisons; never fit away conversion errors."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from .common import digest,read_tensor,save,OUTPUT_SHAPE
from .metrics import evaluate
from ..ply import read_ply


def clouds(reference,candidate):
    a,ca=read_ply(reference);b,cb=read_ply(candidate)
    if not len(a) or not len(b):raise ValueError('Empty cloud comparison')
    # Relative world coordinates are already shared. No extra scale/pose alignment.
    d,idx=cKDTree(a).query(b,k=1)
    reverse,_=cKDTree(b).query(a,k=1)
    return {'reference_points':len(a),'candidate_points':len(b),'point_count_difference':len(b)-len(a),
            'nearest_distance_p50':float(np.median(d)),'nearest_distance_p95':float(np.quantile(d,.95)),
            'reverse_distance_p95':float(np.quantile(reverse,.95)),
            'nearest_rgb_mae':float(np.mean(np.abs(cb.astype(float)-ca[idx].astype(float)))),
            'alignment':'none; same saved poses and relative scale','reference_sha256':digest(reference),'candidate_sha256':digest(candidate)}


def numerical(samples,reference,candidate,backend,model,output):
    manifest=json.loads((Path(samples)/'samples.json').read_text());rows=[]
    if len(manifest['frames'])!=20:raise ValueError('Twenty frozen samples required')
    for f in manifest['frames']:
        if digest(Path(samples)/(f['id']+'.input.f32'))!=f['input_sha256']:raise ValueError('Input hash mismatch')
        value=read_tensor(Path(candidate)/(f['id']+'.output.f32'),OUTPUT_SHAPE)
        row={'id':f['id'],**evaluate(np.load(Path(reference)/(f['id']+'.reference.npy')),value)}
        row['passed']=row['normalized_rmse']<=.03 and row['spearman']>=.98;rows.append(row)
    report={'status':'NUMERICAL_PASS' if all(r['passed'] for r in rows) else 'FAILED','backend':backend,
            'model_sha256':digest(model),'frames':rows,'worst_nrmse':max(r['normalized_rmse'] for r in rows),
            'minimum_spearman':min(r['spearman'] for r in rows),'hardware_inference_verified':backend=='dpu'}
    if backend=='dpu':
        worker=json.loads((Path(candidate)/'worker.json').read_text())
        if worker['backend']!='dpu' or not worker['hardware_inference_verified'] or worker['model_sha256']!=report['model_sha256']:
            raise ValueError('Real matching DPU worker output required')
        if [r['id'] for r in worker['frames']]!=[f['id'] for f in manifest['frames']]:raise ValueError('DPU output order mismatch')
        for f,r in zip(manifest['frames'],worker['frames']):
            if r['input_sha256']!=f['input_sha256'] or r['output_sha256']!=digest(Path(candidate)/(f['id']+'.output.f32')):raise ValueError('DPU output provenance mismatch')
    save(output,report);return report


def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    c=s.add_parser('clouds')
    for key in ['reference','candidate','output']:c.add_argument('--'+key,type=Path,required=True)
    n=s.add_parser('numerical')
    for key in ['samples','reference','candidate','model','output']:n.add_argument('--'+key,type=Path,required=True)
    n.add_argument('--backend',required=True,choices=['reference','quantized-reference','dpu'])
    a=vars(p.parse_args());cmd=a.pop('command')
    if cmd=='clouds':
        output=a.pop('output');report=clouds(**a);save(output,report)
    else:report=numerical(**a)
    print(json.dumps({k:v for k,v in report.items() if k!='frames'}))
    if report.get('status')=='FAILED':raise SystemExit(1)

if __name__=='__main__':main()
