"""Package the Linux/PC integration increment, excluding credentials and datasets."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import zipfile


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[2];job=a.job.resolve()
    full=job/'slam_full_2273'
    state=json.loads((full/'status.json').read_text())
    exact=json.loads((job/'board_exact_9frames/result.json').read_text())
    assert exact['status']=='PASS' and len(exact['runs'])==9
    assert state['integration_pass'] and state['exit_code']==0 and state['frames']==2273
    assert state['cpu_orb_calls']==0 and state['hardware_requests']==2273
    tracking=list(csv.DictReader((full/'TrackingStates.csv').open()))
    first=next(i for i,r in enumerate(tracking) if int(r['state_after'])==2)
    assert len(tracking)==2273 and all(int(r['state_after'])==2 for r in tracking[first:])
    poses=[[float(v) for v in line.split()] for line in (full/'CameraTrajectory.txt').read_text().splitlines() if line.strip()]
    assert len(poses)==2163 and all(len(r)==8 and all(math.isfinite(x) for x in r) for r in poses)
    assert all(abs(sum(x*x for x in r[4:])-1)<1e-3 for r in poses)
    assert all(a[0]<b[0] for a,b in zip(poses,poses[1:]))
    span=[max(r[i] for r in poses)-min(r[i] for r in poses) for i in (1,2,3)]
    assert sum(x*x for x in span)>1e-4
    keyframes=sum(bool(line.strip()) for line in (full/'KeyFrameTrajectory.txt').read_text().splitlines())
    proof=dict(status='PASS',scope='Physical FPGA/Ethernet/SLAM integration and finite nonconstant trajectory',
               frames=2273,first_tracking_index=first,tracked_frames=len(poses),keyframe_poses=keyframes,
               cpu_orb_calls=0,post_initialization_lost_frames=0,trajectory_extent_arbitrary_scale=span,
               pose_accuracy='not validated: provisional intrinsics; monocular arbitrary scale')
    (job/'integration_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
    files={}
    def add(path,name):
        assert path.is_file(),path
        assert name not in files,name
        files[name]=path
    for path in (root/'orb60/linux').glob('*'):
        if path.is_file():add(path,'orb60/linux/'+path.name)
    for name in ('board_ssh.py','prepare_linux.py','build_linux.ps1','install_slam_network.py','run_slam_network.py','package_linux.py'):
        add(root/'orb60/scripts'/name,'orb60/scripts/'+name)
    for name in ('0016-zynq-network-orb.patch','0017-fpga-multiscale-initialization.patch','FpgaORB.h'):
        add(root/'rk3588/orbslam3_cpu_baseline/patches'/name,'rk3588/orbslam3_cpu_baseline/patches/'+name)
    report=root/'orb60/docs/LINUX_ETHERNET_SLAM_BRINGUP_20261021_ZH.md'
    add(report,'README_ZH.md')
    for name in ('orb60_150mhz.bit','orb60_150mhz.bit.bin','orb60-server-arm','board-probe','acz7015-orb60.dtbo',
                 'orb60_registers.h','xfastv2_layer2_hls_hw.h','xfastv2_descriptor_hls_hw.h','firmware.sha256','manifest.json'):
        add(job/name,'artifacts/'+name)
    for name in ('board_load.log','board_server.log','integration_validation.json'):
        add(job/name,'evidence/'+name)
    for directory,names in (
        ('board_exact_9frames',('result.json',)),('init_diagnostic',('matches.json',)),
        ('slam_300',('status.json',)),('slam_multiscale_300',('status.json',)),
        ('slam_full_2273',('status.json','output.log','TrackingStates.csv','FeatureTimeStats.csv','MapStateStats.csv',
                           'CameraTrajectory.txt','KeyFrameTrajectory.txt','Diagnostics_maps.csv'))):
        for name in names:add(job/directory/name,'evidence/'+directory+'/'+name)
    destination=job/'orb60_linux_fpga_slam_150mhz_20261021.zip'
    assert not destination.exists(),'Preserve the previous package'
    manifest={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sorted(files.items())}
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()):archive.write(path,name)
        archive.writestr('SHA256SUMS.txt',''.join(f'{h}  {name}\n' for name,h in manifest.items()))
    with zipfile.ZipFile(destination) as archive:assert archive.testzip() is None
    result=dict(proof,package=str(destination),package_bytes=destination.stat().st_size,
                package_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),files=len(files)+1,
                scope='Integration increment: PS/Linux source+ARM ELF+SLAM patches+paired bit/bin+evidence; original HLS/SLAM project dependencies retained in workspace')
    (job/'delivery.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
