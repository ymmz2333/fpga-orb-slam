"""Actual 7015 PL -> KV260 fixed-map PS geometry, with sealed DPU RGB map display.

Depth is not inferred again during fixed-map localization. Saved DPU blocks
must belong to the exact sealed sparse map. This is separate from live mapping.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import zlib
import cv2
from orb60.demo_bridge.protocol import Packet,Kind,PROFILE,receive
from orb60.dense.live_server import DeltaServer
from .localization_bundle import load as load_bundle
from .localization_telemetry import LocalTelemetry,LatestLocalizationTelemetry
from .network_frontend import NetworkFrontend
from .run_network_system import load,save,rows,digest
from .run_system import VideoSource
from .source_frame_map import SourceFrameMap


def produce(listener,capture,frontend,camera,identities,reference,out,telemetry,stop,errors,report):
    journal=None;mapping=None
    try:
        mapping=SourceFrameMap(out/'source_frames.csv')
        journal=(out/'physical_frames.csv').open('w',newline='')
        fields=('source_frame_id','timestamp_ns','gray_crc','record_crc','count','cpu_orb_calls','engine_ns','network_ns',
                'input_ms','pl_ms','ps_roundtrip_ms','preview_ms','whole_ms')
        writer=csv.DictWriter(journal,fieldnames=fields);writer.writeheader()
        camera=Path(camera).read_bytes();sha=hashlib.sha256(camera).hexdigest()
        peer,_=listener.accept();peer.settimeout(120)
        peer.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        with peer:
            hello=receive(peer)
            if hello.kind!=Kind.HELLO or hello.body!=sha.encode():raise ValueError('Localizer camera hash mismatch')
            peer.sendall(Packet(Kind.HELLO,body=(sha+'\n'+PROFILE+'\n').encode()+camera).encode())
            started=time.monotonic_ns();report['started_processing_monotonic_ns']=started
            last=None;next_preview=0
            for i,identity in enumerate(identities):
                loop_started=time.monotonic_ns()
                if stop.is_set():raise RuntimeError('Cancelled producer is incomplete')
                ok,bgr=capture.read()
                if not ok or bgr.shape!=(720,960,3):raise ValueError('Missing original video frame')
                stamp=capture.timestamp_ns;gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY);pixels=gray.tobytes();crc=zlib.crc32(pixels)
                if (i,stamp,crc)!=(int(identity['source_frame_id']),int(identity['timestamp_ns']),int(identity['gray_crc'])):
                    raise ValueError('Frozen input identity mismatch at frame%d'%i)
                decoded=time.monotonic_ns()
                payload,result=frontend.run(gray,i,stamp);record_crc=zlib.crc32(result['records'])
                if (result['count'],record_crc)!=(int(reference[i]['count']),int(reference[i]['record_crc'])):
                    raise ValueError('Frozen physical feature mismatch at frame%d'%i)
                mapping.append(stamp,i)
                packet=Packet(Kind.FRAME,1,i,stamp,result['count'],crc,0,pixels+payload)
                pl_done=time.monotonic_ns()
                peer.sendall(packet.encode());ack=receive(peer)
                if (ack.kind,ack.session,ack.frame,ack.stamp)!=(Kind.ACK,1,i,stamp):raise ValueError('Localizer ACK identity mismatch')
                state=json.loads(ack.body)
                if (state['source_frame_id'],state['timestamp_ns'],state['features'])!=(i,stamp,result['count']):
                    raise ValueError('Localizer ACK payload identity mismatch')
                if state['mapping'] or state['cpu_orb_calls']:raise ValueError('Fixed-map PS boundary violation')
                ps_done=time.monotonic_ns()
                report['frames']=i+1;report['valid_poses']+=int(state['pose_valid'])
                now=time.monotonic_ns()
                if now>=next_preview or i==len(identities)-1:
                    telemetry.publish(packet,ack,gray,bgr=bgr);next_preview=now+100000000
                finished=time.monotonic_ns()
                writer.writerow(dict(source_frame_id=i,timestamp_ns=stamp,gray_crc=crc,record_crc=record_crc,count=result['count'],
                                     cpu_orb_calls=0,engine_ns=result['engine_ns'],network_ns=result['roundtrip_ns'],
                                     input_ms=(decoded-loop_started)*1e-6,pl_ms=(pl_done-decoded)*1e-6,
                                     ps_roundtrip_ms=(ps_done-pl_done)*1e-6,preview_ms=(finished-ps_done)*1e-6,
                                     whole_ms=(finished-loop_started)*1e-6))
                if (i+1)%30==0 or i==len(identities)-1:
                    journal.flush();save(out/'progress.json',dict(frames=i+1,valid_poses=report['valid_poses'],seconds=(now-started)*1e-9))
                last=packet
            if report['full_input'] and capture.read()[0]:raise ValueError('Extra unindexed video frame')
            peer.sendall(Packet(Kind.END,1,last.frame,last.stamp).encode());ack=receive(peer)
            if (ack.kind,ack.session,ack.frame,ack.stamp)!=(Kind.ACK,1,last.frame,last.stamp):raise ValueError('Localizer drain mismatch')
            report['completed_processing_monotonic_ns']=time.monotonic_ns()
            report['processing_seconds']=(report['completed_processing_monotonic_ns']-started)*1e-9
            report['processing_fps']=len(identities)/report['processing_seconds']
    except BaseException as error:errors.append(repr(error));stop.set()
    finally:
        if journal:journal.close()
        if mapping:mapping.close()
        try:
            telemetry.finish(not errors)
            report['preview_frames']=telemetry.telemetry.written;report['preview_replaced']=telemetry.replaced
        except BaseException as error:errors.append(repr(error));stop.set()
        frontend.close();capture.release();listener.close()


def run(config_path,output,frames=0):
    if platform.machine()!='aarch64' or not sys.platform.startswith('linux'):raise ValueError('Actual KV260 required')
    cv2.setNumThreads(1)
    config=load(config_path);root=Path(config['root']).resolve();out=Path(output).resolve()
    def path(key):
        value=Path(config[key]);return value if value.is_absolute() else root/value
    identities=rows(path('identities'));reference=rows(path('reference_features'))
    if frames<0 or frames>len(identities):raise ValueError('Invalid bounded frame count')
    if frames:identities=identities[:frames]
    if not identities or len(reference)<len(identities):raise ValueError('Incomplete input/reference')
    for i,r in enumerate(identities):
        if int(r['source_frame_id'])!=i:raise ValueError('Unordered input identities')
    bundle=load_bundle(path('bundle'),path('camera'))
    if not bundle.get('dense') or not bundle['dense'].get('hardware_inference_verified') or bundle['dense']['backend']!='kv260_dpu':
        raise ValueError('Exact-map actual DPU RGB blocks required')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',scope='Actual PL fixed-map localization; displaying previously generated same-map DPU RGB blocks',
                cpu_orb_calls=0,mapping=False,live_depth_inference=False,frames=0,valid_poses=0,full_input=frames==0,
                config=config,map_version=bundle['map']['version'],pids={},file_sha256={str(path(k)):digest(path(k)) for k in ('video','identities','reference_features','localizer')})
    authored=Path(__file__).resolve().parent
    report['source_sha256']={str(p.relative_to(authored.parents[1])):digest(p) for p in (
        authored/'run_network_localization.py',authored/'network_frontend.py',authored/'localization_telemetry.py',
        authored/'localization_bundle.py',authored/'gui.py',authored/'gui_worker.py',authored/'run_system.py',
        authored/'video_conversion.py',authored.parent/'linux/client.py')}
    save(out/'RESULT.json',report)
    children=[];logs=[];thread=None;frontend=None;server=None;stop=threading.Event();errors=[];listener=None;telemetry=None
    try:
        telemetry=LatestLocalizationTelemetry(LocalTelemetry(path('bundle'),out/'tracking/telemetry'))
        server=DeltaServer(out,'127.0.0.1',int(config.get('localization_dense_port',18791)),telemetry=telemetry.folder,input_kind='kv260_local_rgb')
        for stem in bundle['dense']['blocks']:
            folder=path('bundle')/'dense_blocks';meta=load(folder/(stem+'.final.json'));payload=(folder/(stem+'.final.bin')).read_bytes()
            if meta['map_id']!=bundle['map']['map_id'] or meta['source']!='kv260_dpu' or hashlib.sha256(payload).hexdigest()!=meta['payload_sha256']:
                raise ValueError('Fixed-map RGB block provenance mismatch')
            server.publish(meta,payload)
        frontend=NetworkFrontend(config['endpoint']);capture=VideoSource(path('video'),bool(config.get('decoder_reuse_converter',False)))
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(120)
        port=listener.getsockname()[1]
        def launch(command,name,env=None):
            log=(out/(name+'.log')).open('w');logs.append(log)
            child=subprocess.Popen([str(x) for x in command],stdout=log,stderr=subprocess.STDOUT,cwd=root/'sources',env=env,start_new_session=True)
            children.append(child);report['pids'][name]=child.pid;return child
        native=launch([path('localizer'),'stream',path('camera'),path('bundle')/'map.zslmap','127.0.0.1',port,out/'localization'],'localizer')
        thread=threading.Thread(target=produce,args=(listener,capture,frontend,path('camera'),identities,reference,out,telemetry,stop,errors,report),daemon=True);thread.start()
        env={**os.environ,'ORB60_GUI_SOURCE_SCOPE':'two_board_live','ORB60_GUI_TASK_MODE':'fixed_map_localization',
             'ORB60_GUI_STOP_FILE':str(out/'stop_gui'),'ORB60_GUI_LIVE_STATUS':str(out/'gui_live.json'),
             'ORB60_GUI_INPUT_IDENTITIES':str(path('identities'))}
        env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',OPENCV_FOR_THREADS_NUM='1')
        for key in ('QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_FONTDIR'):env.pop(key,None)
        gui=launch([path('gui_python'),'-m','orb60.kv260.gui','--dense-live','127.0.0.1:'+str(config.get('localization_dense_port',18791)),
                    '--frame-map',out/'source_frames.csv','--metrics',out/'gpu.json','--screenshot',out/'snapshot'],'gui',env)
        server.state='RUNNING';deadline=time.monotonic()+float(config.get('processing_timeout_seconds',600))
        while native.poll() is None:
            if errors:raise RuntimeError(errors)
            if gui.poll() is not None:raise RuntimeError('GPU viewer stopped before localization drain')
            if time.monotonic()>deadline:raise TimeoutError('Fixed-map localization deadline expired')
            time.sleep(.25)
        thread.join(timeout=20)
        if native.returncode or thread.is_alive() or errors:raise RuntimeError('Incomplete native localization: '+str(errors))
        local=load(out/'localization/LOCALIZATION.json')
        if local['frames']!=len(identities) or not local['valid_poses'] or local['valid_poses']!=report['valid_poses'] or local['geometry_sha256_before']!=local['geometry_sha256_after']:
            raise ValueError('Native fixed-map identity/geometry mismatch')
        load_bundle(path('bundle'),path('camera'))
        server.state='COMPLETED';deadline=time.monotonic()+60
        while True:
            state=load(out/'gui_live.json') if (out/'gui_live.json').exists() else {}
            if state.get('error'):raise ValueError('GPU stream error: '+state['error'])
            if state.get('state')=='COMPLETED' and state.get('frame')==len(identities)-1 and len(state.get('dense_revisions',{}))==len(server.chunks):break
            if gui.poll() is not None or time.monotonic()>deadline:raise TimeoutError('GPU final fixed-map delivery failed')
            time.sleep(.25)
        (out/'stop_gui').touch()
        if gui.wait(timeout=20):raise RuntimeError('GPU viewer did not close cleanly')
        gpu=load(out/'gpu.json')
        for name in ('gpu','gpu_sparse'):
            item=gpu.get(name,{})
            if item.get('software',True) or item.get('vendor')!='ARM' or 'Mali' not in item.get('renderer','') or item.get('paints',0)<1:
                raise ValueError('Hardware Mali window not verified: '+name)
        if gpu['last_frame']!=len(identities)-1 or not gpu.get('dense_points'):raise ValueError('Missing final localization display')
        report.update(status='ACTUAL_TWO_BOARD_FIXED_MAP_COMPONENT_PASS',localization=local,gpu=gpu,gui_live=state,
                      valid_ratio=report['valid_poses']/report['frames'],source_identity_mismatches=0,physical_feature_mismatches=0,
                      whole_system_target_evaluated=False)
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        stop.set()
        if frontend:frontend.close()
        if listener:listener.close()
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        if thread:thread.join(timeout=20)
        if server:server.close()
        for log in logs:log.close()
        save(out/'RESULT.json',report)
    print(json.dumps({k:report.get(k) for k in ('status','frames','valid_poses','valid_ratio','processing_seconds','processing_fps','live_depth_inference')}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=int,default=0);a=p.parse_args();run(a.config,a.output,a.frames)
