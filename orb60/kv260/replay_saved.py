"""Diagnostic PS replay of saved real PL records; never claims current KV260 PL."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import threading
import time
import zlib

from orb60.demo_bridge.protocol import Packet,Kind,PROFILE,receive,validate_frame
from .camera_contract import validate_pair


def serve(listener,capture,video,camera,limit,ready,color_store=None):
    import av
    with (capture/'frames.csv').open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))[:limit]
    if not rows:raise ValueError('No saved FPGA transactions')
    selected={int(row['source_frame_index']):row for row in rows}
    if len(selected)!=len(rows):raise ValueError('Duplicate source frame')
    digest=hashlib.sha256(camera).hexdigest();ready.set()
    conn,_=listener.accept()
    with conn,av.open(str(video)) as movie,(capture/'features.bin').open('rb') as features,(capture/'runtime.bin').open('rb') as runtime:
        conn.settimeout(120);hello=receive(conn)
        if hello.kind!=Kind.HELLO or hello.body.decode()!=digest:raise ValueError('Calibration handshake mismatch')
        conn.sendall(Packet(Kind.HELLO,body=(digest+'\n'+PROFILE+'\n').encode()+camera).encode())
        previous=-1;session=1;sent=0;last=None
        for index,frame in enumerate(movie.decode(video=0)):
            if index not in selected:continue
            row=selected[index];fid=int(row['frame_index']);stamp=int(row['timestamp_ns']);count=int(row['count'])
            if stamp<=previous or not 0<=count<=1000:raise ValueError('Invalid saved timestamp/count')
            previous=stamp;gray=frame.to_ndarray(format='gray').tobytes()
            if len(gray)!=960*720 or hashlib.sha256(gray).hexdigest()!=row['gray_sha256']:raise ValueError('Decoded gray differs from original PL input')
            features.seek(int(row['record_offset'])*64);records=features.read(count*64)
            if hashlib.sha256(records).hexdigest()!=row['records_sha256'] or zlib.crc32(records)!=int(row['record_crc32']):raise ValueError('Saved PL record checksum mismatch')
            runtime.seek(fid*1152);stats=runtime.read(1152)
            if len(stats)!=1152:raise ValueError('Missing saved runtime metadata')
            packet=Packet(Kind.FRAME,session,fid,stamp,count,zlib.crc32(gray),0,gray+stats[:128]+records+stats[128:])
            validate_frame(packet);conn.sendall(packet.encode());ack=receive(conn)
            if (ack.kind,ack.session,ack.frame,ack.stamp)!=(Kind.ACK,session,fid,stamp):raise ValueError('Frame ACK mismatch')
            if color_store is not None:
                status=json.loads(ack.body)
                if status.get('depth_keyframe_selected'):
                    import numpy as np
                    color_store.publish(fid,stamp,frame.to_ndarray(format='bgr24'),np.frombuffer(gray,np.uint8).reshape(720,960))
            sent+=1;last=packet
            if sent%50==0:print('SAVED_PL_PS_REPLAY frames='+str(sent),flush=True)
            if sent==len(rows):break
        if sent!=len(rows):raise ValueError('Video ended before all paired records')
        conn.sendall(Packet(Kind.END,session,last.frame,last.stamp).encode());ack=receive(conn)
        if (ack.kind,ack.session,ack.frame,ack.stamp)!=(Kind.ACK,session,last.frame,last.stamp):raise ValueError('Drain ACK mismatch')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('executable','vocabulary','yaml','camera','capture','video','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--frames',type=int,default=300);a=p.parse_args()
    if a.output.exists() or not 1<=a.frames<=2273:p.error('Fresh output and frame count 1..2273 required')
    validate_pair(a.camera,a.yaml)
    root=a.output.resolve();root.parent.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(180)
    errors=[];ready=threading.Event()
    def worker():
        try:serve(listener,a.capture,a.video,a.camera.read_bytes(),a.frames,ready)
        except BaseException as error:errors.append(repr(error));ready.set()
        finally:listener.close()
    thread=threading.Thread(target=worker,daemon=True);thread.start();ready.wait(15)
    if errors:raise RuntimeError(errors)
    command=[str(a.executable.resolve()),str(a.vocabulary.resolve()),str(a.yaml.resolve()),str(a.camera.resolve()),'127.0.0.1',str(listener.getsockname()[1]),str(root),str(root/'telemetry')]
    start=time.monotonic();result=subprocess.run(command);thread.join(timeout=10)
    report=dict(backend='saved_physical_PL_records_on_KV260_PS',live_kv260_pl=False,frames_requested=a.frames,
                exit_code=result.returncode,producer_errors=errors,producer_finished=not thread.is_alive(),wall_seconds=time.monotonic()-start)
    rows=[]
    if (root/'frames.csv').exists():
        with (root/'frames.csv').open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    report.update(frames=len(rows),cpu_orb_calls=sum(int(row['cpu_orb_calls']) for row in rows),valid_poses=sum(int(row['pose_valid']) for row in rows),map_export_complete=(root/'map/EXPORT_COMPLETE').exists())
    map_checks=False
    if report['map_export_complete']:
        try:
            def table(name):
                with (root/'map'/name).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
            points=table('points.csv');keys=table('keyframes.csv');observations=table('observations.csv')
            report.update(map_points=len(points),map_keyframes=len(keys),map_observations=len(observations))
            map_checks=bool(points and keys and observations)
            map_checks &= (root/'map/representative_descriptors.bin').stat().st_size==32*len(points)
            map_checks &= (root/'map/observation_descriptors.bin').stat().st_size==32*len(observations)
            map_checks &= all(math.isfinite(float(row[k])) for row in points for k in ('x','y','z'))
            map_checks &= all(math.isfinite(float(row[f'twc_{r}{c}'])) for row in keys for r in range(4) for c in range(4))
            map_checks &= all(abs(float(row[f'twc_3{c}'])-(1.0 if c==3 else 0.0))<1e-4 for row in keys for c in range(4))
        except (OSError,ValueError,KeyError) as error:report['map_validation_error']=str(error)
    report['map_files_valid']=bool(map_checks)
    report['status']='PASS' if result.returncode==0 and not errors and not thread.is_alive() and len(rows)==a.frames and report['cpu_orb_calls']==0 and report['valid_poses']>0 and report['map_export_complete'] and map_checks else 'FAIL'
    root.mkdir(parents=True,exist_ok=True);(root/'KV260_PS_REPLAY.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
