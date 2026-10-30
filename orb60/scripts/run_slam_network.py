"""Bounded PC replay through real FPGA extraction and WSL ORB-SLAM3."""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import platform
from pathlib import Path
import statistics
import shutil
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--slam-root',type=Path,required=True)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--camera',type=Path,required=True)
    p.add_argument('--host',required=True,help='IPv4:port or [IPv6%%interface]:port')
    p.add_argument('--frames',type=int,default=300,help='0 means the full sequence')
    p.add_argument('--platform',choices=('pc','rk3588'),default='pc')
    p.add_argument('--feature-mode',choices=('fpga','fpga-pipeline'),default='fpga')
    p.add_argument('--unpaced',action='store_true',help='Measure processing throughput without replay sleeps')
    p.add_argument('--telemetry',action='store_true',help='Export latest visualization snapshot asynchronously')
    p.add_argument('--telemetry-record',action='store_true',help='Retain exported snapshots for desktop replay')
    p.add_argument('--telemetry-fps',type=float,default=30,help='Display sample limit1..60; independent of SLAM frame processing')
    p.add_argument('--interface',default='',help='Record the direct FPGA LAN route and interface counters')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--executable',type=Path,help='Optional paired frontend using the unchanged accepted SLAM library')
    p.add_argument('--library-directory',type=Path,help='Private directory of the paired SLAM library')
    p.add_argument('--cpu-affinity',help='Optional Linux core list, e.g. 4-7')
    a=p.parse_args()
    if not 1<=a.telemetry_fps<=60:p.error('--telemetry-fps must be1..60')
    a.slam_root=a.slam_root.resolve();a.dataset=a.dataset.resolve();a.camera=a.camera.resolve();a.output=a.output.resolve()
    a.output.mkdir(parents=True,exist_ok=False)
    stamps=(a.dataset/'timestamps.txt').read_text().splitlines()
    stamps=[s.strip() for s in stamps if s.strip()]
    assert all(int(x)<int(y) for x,y in zip(stamps,stamps[1:]))
    if a.frames>0:stamps=stamps[:a.frames]
    assert len(stamps)>1
    times=a.output.resolve()/'timestamps.txt';times.write_text('\n'.join(stamps)+'\n')
    executable=a.executable.resolve() if a.executable else a.slam_root/'Examples/Monocular/mono_euroc'
    cmd=[str(executable),str(a.slam_root/'Vocabulary/ORBvoc.txt'),str(a.camera.resolve()),
         str(a.dataset.resolve()),str(times),'--no-viewer','--feature-mode',a.feature_mode,'--feature-dir',a.host]
    if a.unpaced:cmd.append('--unpaced')
    if a.telemetry or a.telemetry_record:
        cmd+=['--telemetry-dir',str(a.output/'telemetry')]
        if a.telemetry_record:cmd.append('--telemetry-record')
        if (a.dataset/'frames.csv').is_file():shutil.copy2(a.dataset/'frames.csv',a.output/'source_frames.csv')
    if a.cpu_affinity:
        import re
        if not re.fullmatch(r'[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*',a.cpu_affinity):p.error('Invalid CPU core list')
        cmd=['taskset','-c',a.cpu_affinity]+cmd
    def counters():
        result={}
        for node in Path('/sys/class/net').iterdir():
            try:result[node.name]={key:int((node/'statistics'/key).read_text()) for key in
                                  ('rx_bytes','tx_bytes','rx_errors','tx_errors','rx_dropped','tx_dropped')}
            except OSError:pass
        return result
    network_before=counters() if a.interface else {}
    route=''
    if a.interface:
        assert a.interface in network_before,'interface not present'
        host=a.host[1:a.host.index(']')] if a.host.startswith('[') else a.host.split(':')[0]
        address=host.split('%')[0]
        route=subprocess.check_output(['ip','-6' if ':' in address else '-4','route','get',address,'oif',a.interface],text=True)
        assert 'dev '+a.interface in route,'FPGA route differs from selected interface'
    state=dict(state='RUNNING',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               scope='Physical Zynq feature extraction over Ethernet; '+a.platform+' SLAM on recorded video',
               command=cmd,frames=len(stamps),dataset=str(a.dataset),camera_sha256=digest(a.camera),
               initialization_features=1000,normal_features=1000,calibration='borrowed provisional intrinsics, not calibrated',
               execution_platform=a.platform,hostname=platform.node(),architecture=platform.machine(),
               network_interface=a.interface,fpga_route=route,network_before=network_before)
    state.update(feature_mode=a.feature_mode,unpaced=a.unpaced)
    state.update(telemetry=a.telemetry or a.telemetry_record,telemetry_record=a.telemetry_record,telemetry_fps=a.telemetry_fps)
    state['executable_sha256']=digest(executable)
    library_directory=a.library_directory.resolve() if a.library_directory else a.slam_root/'lib'
    state['library_sha256']=digest(library_directory/'libORB_SLAM3.so')
    state['library_directory']=str(library_directory)
    state['source_sha256']={name:digest(a.slam_root/name) for name in (
        'include/FpgaORB.h','include/Orb60Protocol.h','include/FeatureIO.h','src/FeatureIO.cc','src/Tracking.cc','src/ORBmatcher.cc',
        'include/FpgaPipeline.h','include/FpgaReplayInput.h','include/System.h','src/System.cc',
        'include/OrbTelemetry.h','Examples/Monocular/mono_euroc.cc') if (a.slam_root/name).exists()}
    status=a.output/'status.json'
    def save():status.write_text(json.dumps(state,indent=2)+'\n')
    save();env=os.environ.copy();install=a.slam_root.parent.parent/'install/lib'
    env['ORB60_VIEWER_FPS']=str(a.telemetry_fps)
    env['LD_LIBRARY_PATH']=str(install)+':'+env.get('LD_LIBRARY_PATH','')
    if a.library_directory:env['LD_LIBRARY_PATH']=str(library_directory)+':'+env['LD_LIBRARY_PATH']
    start=time.monotonic()
    with (a.output/'output.log').open('w') as log:
        process=subprocess.Popen(cmd,cwd=a.output,env=env,stdout=log,stderr=subprocess.STDOUT)
        state['process_id']=process.pid;save()
        code=process.wait()
    state.update(exit_code=code,wall_seconds=time.monotonic()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    import resource
    state['peak_child_rss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if a.interface:
        network_after=counters();state['network_after']=network_after
        state['network_delta']={name:{key:network_after[name][key]-value for key,value in values.items()}
                                for name,values in network_before.items() if name in network_after}
    try:
        assert code==0,'SLAM process failed; inspect output.log'
        rows=list(csv.DictReader((a.output/'FeatureTimeStats.csv').open()))
        tracking=list(csv.DictReader((a.output/'TrackingStates.csv').open()))
        assert len(rows)==len(stamps)==len(tracking),'incomplete replay'
        assert all(int(r['extractor_calls'])==0 and float(r['native_ms'])==0 for r in rows),'CPU ORB fallback detected'
        calls=sum('FPGA_ORB_NET frame=' in line for line in (a.output/'output.log').read_text().splitlines())
        assert calls==len(stamps),'missing hardware feature request'
        states=collections.Counter(int(r['state_after']) for r in tracking)
        trajectory=a.output/'CameraTrajectory.txt'
        poses=sum(bool(s.strip()) for s in trajectory.read_text().splitlines()) if trajectory.exists() else 0
        state.update(state='COMPLETED',feature_frames=len(rows),hardware_requests=calls,cpu_orb_calls=0,
                     tracking_states=dict(states),trajectory_poses=poses,
                     initialized=bool(states.get(2,0)),scope='Physical FPGA + Ethernet + '+a.platform+' SLAM integration; accuracy not calibrated')
        for field in ('count','read_ms','decode_ms'):
            values=[float(r[field]) for r in rows]
            state[field]=dict(min=min(values),mean=statistics.mean(values),max=max(values))
        state['integration_pass']=bool(states.get(2,0) and poses)
        import re
        log_text=(a.output/'output.log').read_text()
        def distribution(values):
            values=sorted(values)
            return dict(mean=statistics.mean(values),p99=values[max(0,(99*len(values)+99)//100-1)],max=max(values))
        for field in ('network_ms','wait_ms','latency_ms'):
            values=[float(v) for v in re.findall(r'\b'+field+r'=([\d.eE+-]+)',log_text)]
            if values:state[field]=distribution(values)
        replay=re.search(r'REPLAY_SUMMARY frames=(\d+) seconds=([\d.eE+-]+) fps=([\d.eE+-]+)',log_text)
        if replay:
            assert int(replay[1])==len(stamps)
            state['processing_seconds']=float(replay[2]);state['processing_fps']=float(replay[3])
        if a.feature_mode=='fpga-pipeline':
            summary=re.search(r'FPGA_PIPELINE_SUMMARY sent=(\d+) received=(\d+) consumed=(\d+) max_inflight=(\d+) max_input=(\d+) max_results=(\d+)',log_text)
            assert summary and all(int(summary[i])==len(stamps) for i in (1,2,3)),'pipeline incomplete drain'
            assert all(int(summary[i])<=3 for i in (4,5,6)),'unbounded pipeline'
            state['pipeline']=dict(zip(('sent','received','consumed','max_inflight','max_input','max_results'),map(int,summary.groups())))
        save()
        print(json.dumps(state,indent=2),flush=True)
        return 0 if state['integration_pass'] else 3
    except Exception as exc:
        state.update(state='FAILED',error=str(exc));save();raise


if __name__=='__main__':
    raise SystemExit(main())
