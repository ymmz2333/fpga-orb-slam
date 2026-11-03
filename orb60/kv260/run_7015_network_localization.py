"""KV260 supplies pixels; physical7015 performs ORB, fixed-map pose and HDMI.

Recorded diagnostic and actual live camera inputs are mutually exclusive.
The latter requires its matching installed map unless explicitly testing input
with no map. No KV260 localization or inference is substituted for7015 PS.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import time
import itertools
from .camera_input import Camera,validate_calibration,validate_pair
from .network_frontend import endpoint
from .localization_input import Sender,SIZE
from .two_board_session import Board,extract_evidence
from .run_network_system import digest,rows,save
from .peer_link import transport_failure


def parts(folder,kind):
    result=[]
    paths=sorted(Path(folder).glob(kind+'.part*.csv'))
    plain=Path(folder)/(kind+'.csv')
    if plain.exists():
        if paths:raise ValueError('Mixed rotating and manual CSV journals')
        paths=[plain]
    for p in paths:result.extend(rows(p))
    return result


def compare_recorded(actual,baseline):
    poses,reference=parts(actual,'poses'),parts(baseline,'poses')
    timing,reference_timing=parts(actual,'timing'),parts(baseline,'timing')
    if (not poses or len(poses)>len(reference) or len(timing)!=len(poses) or
        len(reference_timing)!=len(reference)):raise ValueError('Incomplete paired native localization rows')
    maximum=0.0
    for a,b,t,u in zip(poses,reference,timing,reference_timing):
        for key in ('frame_id','timestamp_ns','map_version','pose_valid'):
            if a[key]!=b[key]:raise ValueError('Native paired pose identity/validity changed: '+key)
        for key in ('features','pose_valid','matches','inliers'):
            if t[key]!=u[key]:raise ValueError('Native paired localization metric changed: '+key)
        fields=('tx','ty','tz','r00','r01','r02','r10','r11','r12','r20','r21','r22')
        for key in fields:
            if bool(a[key])!=bool(b[key]):raise ValueError('Invalid native pose cannot contain a fabricated matrix')
            if a[key]:
                left,right=float(a[key]),float(b[key])
                if not math.isfinite(left) or not math.isfinite(right):raise ValueError('Non-finite native pose matrix')
                maximum=max(maximum,abs(left-right))
    if maximum>1e-10:raise ValueError('7015 pose differs from the retained same-input baseline')
    return dict(frames=len(poses),pose_and_metric_mismatches=0,max_abs_pose_difference=maximum)


def run(a):
    root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    connection=json.loads(a.connection.read_text());board=Board(root,connection,out)
    manual_stop=getattr(a,'manual_stop_file',None)
    manual=manual_stop is not None
    if manual:
        manual_stop=Path(manual_stop).resolve()
        if manual_stop.parent!=out.parent or manual_stop.exists() or a.mode!='live_camera' or a.frames!=0:
            raise ValueError('Explicit live manual source, no frame limit and fresh owned stop file required')
    selected=getattr(a,'fixed_map_multiview',None)
    if selected is None:selected=connection.get('fixed_map_multiview',False)
    if type(selected) is not bool:raise ValueError('Explicit boolean fixed-map view matching selection required')
    host,port=endpoint(a.endpoint)
    if host!=connection['host'] or port!=5605 or not re.fullmatch('/opt/orb-demo/kv260_network_camera_[a-zA-Z0-9_]+',a.release):
        raise ValueError('Explicit matching7015 network receiver required')
    if (not manual and not 1<=a.frames<=36000) or a.mode not in ('live_camera','recorded_diagnostic'):
        raise ValueError('Finite explicit source mode required')
    state=dict(status='STARTING',scope=__doc__,input_mode=a.mode,frames_requested=a.frames,frontend='actual7015_PL',
               localization='native7015_PS',display='7015_PS_fixed_RGB_background_plus_PL_HDMI',
               kv260_localization_used=False,dpu_inference_used=False,release=a.release,fixed_map_multiview_selected=selected,manual_control=manual)
    source_rows=None;camera=None;raw=None;sender=None;child=None;log=None
    try:
        calibration=a.camera.read_bytes();calibration_hash=hashlib.sha256(calibration).hexdigest()
        if a.mode=='recorded_diagnostic':
            if not a.fixture or a.allow_unmapped_input_probe:raise ValueError('Explicit recorded fixture required')
            proof=json.loads((a.fixture/'RESULT.json').read_text())
            if proof['status']!='RECORDED_NETWORK_LOCALIZATION_FIXTURE_VERIFIED' or proof['camera_sha256']!=calibration_hash or a.frames>proof['frames']:
                raise ValueError('Recorded fixture/calibration differs')
            if digest(a.fixture/'gray8.bin')!=proof['gray8.bin_sha256'] or digest(a.fixture/'frames.csv')!=proof['frames.csv_sha256']:
                raise ValueError('Recorded source changed')
            source_rows=rows(a.fixture/'frames.csv');raw=(a.fixture/'gray8.bin').open('rb')
        else:
            if a.fixture or not a.library or not a.source_camera:raise ValueError('Actual camera library/source calibration required; no replay fallback')
            validate_calibration(a.source_camera,a.camera)
        name='camera_recorded.csv' if a.mode=='recorded_diagnostic' else 'camera_live.csv'
        board.run('set -eu; test ! -e /run/orb-demo.lock; test "$(cat /sys/class/uio/uio0/version)" = wc1; '
                  '(cd '+shlex.quote(a.release)+' && sha256sum -c SHA256SUMS >/dev/null); '
                  'test "$(sha256sum '+shlex.quote(a.release+'/'+name)+' | cut -d " " -f 1)" = '+calibration_hash,
                  'localization_preflight')
        script='ORB60_NETWORK_MANUAL='+str(int(manual))+' ORB60_FIXED_MAP_MULTIVIEW='+str(int(selected))+' '+shlex.quote(a.release+'/run_network_camera_localization.sh')+' '+a.mode+' '+str(a.frames)
        if a.allow_unmapped_input_probe:script+=' --allow-unmapped-input-probe'
        log=(out/'localizer.log').open('wb');child=subprocess.Popen(board.command+[script],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+25
        while b'NETWORK_LOCALIZER_READY ' not in (out/'localizer.log').read_bytes():
            if child.poll() is not None:raise RuntimeError('7015 localizer stopped before network readiness')
            if time.monotonic()>deadline:raise TimeoutError('7015 localizer readiness expired')
            time.sleep(.1)
        if a.mode=='live_camera':camera=Camera(a.library,a.device,60,'YUYV')
        state['transport_stage']='CONNECT_PIXELS'
        sender=Sender(host,port,calibration,int(a.mode=='recorded_diagnostic'))
        sent=[];began=time.monotonic()
        fields=('frame_id','timestamp_ns','capture_sequence','gray_crc','receipt_ms')
        with (out/'sent_frames.csv').open('w',newline='') as f:
            journal=csv.DictWriter(f,fieldnames=fields);journal.writeheader()
            for i in (itertools.count() if manual else range(a.frames)):
                if manual and i and manual_stop.is_file():break
                if raw:
                    image=raw.read(SIZE);stamp=int(source_rows[i]['timestamp_ns']);sequence=i
                    if len(image)!=SIZE:raise ValueError('Truncated verified recording')
                else:
                    state['transport_stage']='CAPTURE'
                    packed,gray,meta=camera.next();validate_pair(packed,gray,camera.profile())
                    image=gray.tobytes();stamp=meta['timestamp_ns'];sequence=meta['capture_sequence']
                    if i==0 or (not manual and i==a.frames-1):(out/('sample_%d.gray8'%i)).write_bytes(image)
                state['transport_stage']='SEND_PIXELS'
                tick=time.monotonic();crc=sender.send(image,i,stamp,sequence)
                state['transport_stage']='JOURNAL'
                row=dict(frame_id=i,timestamp_ns=stamp,capture_sequence=sequence,gray_crc=crc,receipt_ms=(time.monotonic()-tick)*1000)
                journal.writerow(row);f.flush();sent.append(row)
                if (i+1)%30==0:
                    save(out/'live_progress.json',dict(frames_sent=i+1,last_timestamp_ns=stamp,scope='Image receipt acknowledgments; not pose-validity acceptance'))
                if (i+1)%100==0:print('7015_NETWORK_PIXELS_SENT',i+1,flush=True)
        if manual:
            state['transport_stage']='END_PIXELS'
            sender.finish_manual()
            state['operator_stop_requested']=True
        expected_frames=len(sent)
        state['transport_stage']='VERIFY_DRAINED_RESULT'
        sender.close();sender=None
        if camera:state['camera_profile']=camera.profile();camera.close();camera=None
        if child.wait(timeout=60):raise RuntimeError('7015 native processing or display did not drain normally')
        log.close();log=None
        state['wall_stream_and_drain_seconds']=time.monotonic()-began
        text=(out/'localizer.log').read_text();match=re.search(r'^NETWORK_LOCALIZATION_RUN=(\S+)$',text,re.M)
        if not match or not match[1].startswith(a.release+'/runs/') or not re.fullmatch(r'/[A-Za-z0-9_./-]+',match[1]) or '..' in Path(match[1]).parts:
            raise ValueError('Owned native evidence path invalid')
        state['board_run']=match[1]
        archive=out/'native_reports.tar.gz'
        with archive.open('wb') as f:board.run('tar -czf - -C '+shlex.quote(match[1])+' .','evidence',stdout=f)
        extract_evidence(archive,out/'native');native=out/'native/app'
        if selected and 'FIXED_MAP_MULTIVIEW=1' not in (out/'native/stdout.log').read_text():
            raise ValueError('Native receiver did not enable selected fixed-map view matching')
        received=rows(native/'network_input.csv');timing=parts(native,'timing');poses=parts(native,'poses');rendering=parts(native,'render')
        if not all(len(v)==expected_frames for v in (received,timing,poses,rendering)):raise ValueError('Native image/pose/display rows incomplete')
        if manual and json.loads((native/'network_input.csv.end.json').read_text())!={'status':'OPERATOR_STREAM_END_RECEIVED','frames':expected_frames}:
            raise ValueError('Explicit native manual end/drain receipt required')
        for i,(s,r,t,p) in enumerate(zip(sent,received,timing,poses)):
            if any(int(s[k])!=int(r[k]) for k in ('frame_id','timestamp_ns','capture_sequence','gray_crc')):
                raise ValueError('KV260/7015 actual image identity mismatch')
            if int(t['frame_id'])!=i or int(p['frame_id'])!=i or t['timestamp_ns']!=p['timestamp_ns'] or int(t['timestamp_ns'])!=s['timestamp_ns']:
                raise ValueError('Native PL/PS image ordering mismatch')
            if not 0<int(t['features'])<=1000:raise ValueError('Actual camera frame has no physical ORB features')
        status=json.loads((native/'status.json').read_text());display=json.loads((native/'display.json').read_text())
        if not status['hardware_verified'] or status['hardware_fault'] or status['cpu_orb_calls'] or display['submitted']!=expected_frames or display['underruns'] or display['axi_errors']:
            raise ValueError('Physical7015 PL/HDMI acceptance failed')
        if (out/'native/map_before.txt').read_bytes()!=(out/'native/map_after.txt').read_bytes():raise ValueError('Native localization changed its fixed map')
        valid=sum(int(r['pose_valid']) for r in poses)
        state.update(frames=expected_frames,valid_poses=valid,cpu_orb_calls=0,hardware=status,display=display,
                     background_builds=sum(int(r['background_builds']) for r in rendering),
                     background_hits=sum(int(r['background_hits']) for r in rendering),calibration_sha256=calibration_hash,
                     image_identity_mismatches=0)
        if a.allow_unmapped_input_probe:
            if valid or status['map_version'] or (out/'native/map_before.txt').read_text().strip()!='NO_FIXED_MAP':
                raise ValueError('Unmapped input probe must not claim a valid pose/map')
            state['status']='ACTUAL_KV260_CAMERA_7015_INPUT_PL_HDMI_PROBE_PASS_NO_MAP'
        else:
            if not valid or status['mode']!='LOCAL':raise ValueError('No native fixed-map localization')
            if state['background_builds']!=1 or state['background_hits']!=expected_frames-1:raise ValueError('Fixed colored background not reused')
            if a.baseline_run:
                baseline_archive=out/'baseline.tar.gz'
                with baseline_archive.open('wb') as f:board.run('tar -czf - -C '+shlex.quote(str(a.baseline_run))+' .','baseline',stdout=f)
                extract_evidence(baseline_archive,out/'baseline');state['paired_reference']=compare_recorded(native,out/'baseline')
            elif a.mode=='recorded_diagnostic':raise ValueError('Recorded diagnostic requires the retained native baseline')
            state['status']='ACTUAL_7015_NATIVE_NETWORK_COLOR_LOCALIZATION_COMPONENT_PASS'
    except BaseException as error:
        state.update(status='FAILED',error=repr(error),transport_disconnect=bool(manual and a.mode=='live_camera' and transport_failure(error,state.get('transport_stage'))))
        raise
    finally:
        cleanup_errors=[]
        for obj in (sender,camera,raw):
            if obj:
                try:obj.close()
                except BaseException as error:cleanup_errors.append(repr(error))
        try:
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=20)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        except BaseException as error:cleanup_errors.append(repr(error))
        if log:log.close()
        if cleanup_errors:state.update(status='FAILED',cleanup_errors=cleanup_errors)
        save(out/'RESULT.json',state)
        if cleanup_errors:raise RuntimeError('Owned camera/network child cleanup failed: '+str(cleanup_errors))
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','connection','camera','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--release',required=True);p.add_argument('--endpoint',required=True)
    p.add_argument('--mode',choices=('live_camera','recorded_diagnostic'),required=True);p.add_argument('--frames',type=int,required=True)
    p.add_argument('--fixture',type=Path);p.add_argument('--baseline-run',type=Path)
    p.add_argument('--library',type=Path);p.add_argument('--source-camera',type=Path);p.add_argument('--device',default='/dev/video0')
    p.add_argument('--fixed-map-multiview',action='store_true',default=None)
    p.add_argument('--manual-stop-file',type=Path)
    p.add_argument('--allow-unmapped-input-probe',action='store_true');run(p.parse_args())
