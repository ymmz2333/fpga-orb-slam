"""Actual K26 PL ORB vs immutable physical reference records; no CPU extractor."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
from orb60.kv260.runtime import XrtWorkspace,UioCore,OrbFrontend
from orb60.kv260.dense_fusion import save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','register_map','output'):parser.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    parser.add_argument('--frames',type=int,default=3);args=parser.parse_args()
    if platform.machine()!='aarch64':raise RuntimeError('Actual K26 board required')
    args.output.mkdir(parents=True,exist_ok=False)
    root=args.root.resolve();fixture=root/'replay_300';abi=json.loads(args.register_map.read_text())
    nodes={}
    for node in Path('/sys/class/uio').glob('uio*'):
        name=(node/'name').read_text().strip()
        if name in ('orb60_layer64','orb60_descriptor64'):
            if name in nodes:raise ValueError('Duplicate live ORB UIO node')
            nodes[name]=node
    expected={'layer':('orb60_layer64',0xA0000000),'descriptor':('orb60_descriptor64',0xA0010000)}
    memory=None;cores=[];frontend=None;report={'status':'STARTING','orb_backend':'actual_KV260_PL','cpu_orb_calls':0,'frames':[]}
    try:
        memory=XrtWorkspace();report['buffer_physical_address']=hex(memory.address)
        for key,(name,address) in expected.items():
            node=nodes[name]
            core=UioCore('/dev/'+node.name,name,address,abi[key]);cores.append(core)
            control=core.read('AP_CTRL')
            print('ACTUAL_PL_CONTROL',key,hex(control),flush=True)
            if not control&4:raise RuntimeError('PL core not idle before test: '+key)
        frontend=OrbFrontend(memory,*cores,timeout=5)
        with (fixture/'capture/frames.csv').open(newline='') as f:rows=list(csv.DictReader(f))[:args.frames]
        selected={int(row['source_frame_index']):row for row in rows}
        import av
        with av.open(str(fixture/'video.mp4')) as video,(fixture/'capture/features.bin').open('rb') as records:
            for index,frame in enumerate(video.decode(video=0)):
                if index not in selected:continue
                row=selected[index];gray=frame.to_ndarray(format='gray')
                if hashlib.sha256(gray.tobytes()).hexdigest()!=row['gray_sha256']:raise ValueError('Original PL input gray checksum mismatch')
                records.seek(int(row['record_offset'])*64);expected_records=records.read(int(row['count'])*64)
                if hashlib.sha256(expected_records).hexdigest()!=row['records_sha256']:raise ValueError('Retained reference record checksum mismatch')
                start=time.perf_counter();payload,count=frontend.run(gray);elapsed=time.perf_counter()-start
                actual=payload[128:128+count*64]
                case=dict(source_frame_index=index,features=count,seconds=elapsed,sha256=hashlib.sha256(actual).hexdigest(),
                          expected_sha256=row['records_sha256'],byte_exact=(count==int(row['count']) and actual==expected_records))
                report['frames'].append(case);save(args.output/'SMOKE.json',report)
                if not case['byte_exact']:raise ValueError('Actual K26 PL differs from retained golden records')
                print('K26_ACTUAL_PL_BYTE_EXACT',index,count,round(elapsed,6),'s',flush=True)
                if len(report['frames'])==len(rows):break
        if len(report['frames'])!=args.frames:raise ValueError('Incomplete actual PL test')
        report['status']='ACTUAL_KV260_PL_ORB_BYTE_EXACT_PASS'
    except BaseException as error:
        report.update(status='FAILED',error=repr(error));raise
    finally:
        if frontend and frontend.ever_started:
            while not all(core.read('AP_CTRL')&4 for core in cores):
                report.update(status='HARDWARE_RESET_REQUIRED',error='Active core: buffer retained; no automatic hardware recovery')
                save(args.output/'SMOKE.json',report);time.sleep(1)
        for core in cores:core.close()
        if memory:memory.close()
        save(args.output/'SMOKE.json',report)
    print(report['status'],flush=True)


if __name__=='__main__':main()
