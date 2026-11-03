"""Copy the exact retained7015 recording to KV260 for a paired network-input test."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from orb60.kv260.two_board_session import Board
from orb60.kv260.localization_input import SIZE


def run(root,connection,output):
    root=Path(root).resolve();output=Path(output).resolve();c=json.loads(Path(connection).read_text())
    output.mkdir(parents=True,exist_ok=False);board=Board(root,c,output)
    report=dict(status='RUNNING',scope='Exact recorded diagnostic input only; not current USB camera capture')
    try:
        for key,name in (('raw_index','frames.csv'),('raw','gray8.bin')):
            target=output/name
            if key=='raw' and shutil.disk_usage(output).free<SIZE*report['frames']+512*1024*1024:
                raise ValueError('Insufficient free space for finite recorded fixture')
            command=board.command+['cat '+shlex.quote(c[key])]
            with target.open('wb') as f,(output/(name+'.stderr.log')).open('wb') as error:
                process=subprocess.Popen(command,stdout=f,stderr=error)
                try:code=process.wait(timeout=600)
                finally:
                    if process.poll() is None:process.terminate();process.wait(timeout=10)
            if code:raise RuntimeError('Recorded fixture read failed: '+key)
            digest=hashlib.sha256()
            with target.open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
            if digest.hexdigest()!=c['index_sha256' if key=='raw_index' else 'raw_sha256']:
                raise ValueError('Retained source SHA mismatch: '+name)
            report[name+'_sha256']=digest.hexdigest()
            if key=='raw_index':
                with target.open(newline='') as f:rows=list(csv.DictReader(f))
                if not 1<=len(rows)<=36000:raise ValueError('Finite recorded input required')
                previous=0
                for i,row in enumerate(rows):
                    if int(row['frame_index'])!=i or int(row['byte_offset'])!=i*SIZE or int(row['bytes'])!=SIZE or int(row['timestamp_ns'])<=previous:
                        raise ValueError('Original recorded identity/layout invalid')
                    previous=int(row['timestamp_ns'])
                report['frames']=len(rows)
            elif target.stat().st_size!=SIZE*report['frames']:raise ValueError('Recorded byte count mismatch')
        with (output/'camera_orb.csv').open('wb') as f:
            board.run('cat '+shlex.quote(c['localization_template']+'/map/camera_orb.csv'),'camera',stdout=f)
        report.update(status='RECORDED_NETWORK_LOCALIZATION_FIXTURE_VERIFIED',camera_sha256=hashlib.sha256((output/'camera_orb.csv').read_bytes()).hexdigest())
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:(output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','connection','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
