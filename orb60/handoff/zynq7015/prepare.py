"""Freeze only the paired source/data needed for the independent Zynq handoff."""
import argparse
from pathlib import Path
import shutil
from common import sha,load,save

ROOT=Path(__file__).resolve().parents[3]
PAIR='20261013_194658_frequency_pair_3b981caa'
LAYER='20261013_194659_layer2_c57267c5'
DESC='20261013_190011_descriptor_66d8e6ce'
ROUTE='20261013_202519_orb_150mhz_abbeb794'

def copy(source,target):
    source=Path(source);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha(source)!=sha(target):raise ValueError('Frozen target differs: '+str(target))
    else:shutil.copy2(source,target)

def tree(source,target):
    for path in Path(source).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:copy(path,Path(target)/path.relative_to(source))

def prepare(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    source=ROOT/'orb60/build/dense/room_full'
    for name in ('keyframes.json','slam/keyframes/map_0/keyframes.csv','slam/keyframes/map_0/observations.csv',
                 'slam/TrackingStates.csv','slam/CameraTrajectory.txt','slam/KeyFrameTrajectory.txt','slam/Diagnostics_map0.txt','slam/status.json','slam/output.log'):
        copy(source/name,output/'source_map'/name)
    copy(ROOT/'orb60/build/dense/samples/source_frames.csv',output/'testdata/source_frames.csv')
    video=ROOT/'recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4'
    if sha(video)!='c2ab71867980667111e365ea49ddbc618baa8400b3a5723d10652b204f76a7f4':raise ValueError('Wrong original video')
    copy(video,output/'testdata/video.mp4')
    baseline=output/'fpga_baseline'
    for name,kernel in ((LAYER,'layer2'),(DESC,'descriptor')):
        job=ROOT/'orb60/build/optimized/hls'/name
        for entry in load(job/'source_manifest.json'):
            if sha(job/'inputs'/entry['Path']).lower()!=entry['SHA256'].lower():raise ValueError('Accepted HLS snapshot changed')
        tree(job/'inputs',baseline/kernel/'inputs')
        if kernel=='descriptor':tree(job/'descriptor_vectors',baseline/kernel/'descriptor_vectors')
        for file in ('status.json','source_manifest.json','hls.tcl'):copy(job/file,baseline/kernel/file)
        archive='xilinx_com_hls_fastv2_%s_hls_1_0.zip'%kernel
        copy(job/('projects/%s/solution1/impl/ip/'%kernel)/archive,baseline/'ip'/archive)
    route=ROOT/'orb60/build/optimized/timing'/ROUTE
    tree(route/'inputs',baseline/'top_inputs')
    for report in (route/'reports').glob('*.rpt'):copy(report,baseline/'reports'/report.name)
    copy(route/'status.json',baseline/'route_status.json')
    pair=ROOT/'orb60/build/optimized/comparison'/PAIR
    copy(pair/'bit/orb60_150mhz.bit',baseline/'bit/orb60_150mhz.bit')
    copy(pair/'bit/release_validation.json',baseline/'bit/release_validation.json')
    release_bit=load(pair/'bit/release_validation.json');checkpoint=Path(release_bit['checkpoint'])
    if sha(checkpoint)!=release_bit['checkpoint_sha256']:raise ValueError('Retained routed checkpoint changed')
    copy(checkpoint,baseline/'checkpoint/next_system_routed.dcp')
    if sha(baseline/'bit/orb60_150mhz.bit')!='b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60':raise ValueError('Bit pairing changed')
    for file in ('orb60_registers.h','xfastv2_layer2_hls_hw.h','xfastv2_descriptor_hls_hw.h'):
        copy(ROOT/'orb60/build/linux/reproduce_bringup150_v2'/file,output/'reference/ps'/file)
    release=load(ROOT/'orb60/build/linux/frame_pipeline_20261021/release_manifest.json')
    for file in ('engine.c','engine.h','pipeline.c','pipeline.h','protocol.h','stream_crc.h','client.py','acz7015-orb60.dts',
                 'server.c','board_probe.c','load_board.sh','switch_server.sh','test_engine.c','test_network.py','test_pipeline.py'):
        expected=release['sha256']['orb60/linux/'+file]
        if sha(ROOT/'orb60/linux'/file)!=expected:raise ValueError('PS paired source changed: '+file)
        copy(ROOT/'orb60/linux'/file,output/'reference/ps'/file)
    for file in ('release_manifest.json','compiler_versions.txt','orb60-server-arm','board-probe'):
        copy(ROOT/'orb60/build/linux/frame_pipeline_20261021'/file,output/'reference/ps/retained_build'/file)
    for file in ('kernel_provenance.json','module_info.txt'):
        copy(ROOT/'orb60/build/linux/writecombine_20261021_side'/file,output/'reference/ps_writecombine'/file)
    copy(ROOT/'orb60/build/linux/writecombine_20261021_side/module/orb60_wc_uio.ko',output/'reference/ps_writecombine/retained_build/orb60_wc_uio.ko')
    for file in ('orb60_150mhz.bit.bin','firmware.sha256','acz7015-orb60.dtbo'):
        copy(ROOT/'orb60/build/linux/reproduce_bringup150_v2'/file,baseline/'linux_runtime'/file)
    for directory in ('ps_copy64','ps_writecombine'):
        folder=ROOT/'orb60/experiments'/directory
        for path in folder.iterdir():
            if path.is_file() and path.suffix in ('.c','.h','.md',''):
                copy(path,output/'reference'/directory/path.name)
    for directory in ('ps_copy64','ps_writecombine'):
        folder=ROOT/'orb60/experiments'/directory
        for path in folder.glob('*.sh'):copy(path,output/'reference'/directory/path.name)
    save(output/'preparation.json',dict(status='PREPARED_PENDING_PHYSICAL_CAPTURE_AND_LOCALIZATION',
        original_video_sha256=sha(video),device='xc7z015clg485-2',clock_mhz=150,ppc=4,
        retained_route=dict(wns_ns=.093,whs_ns=.036,slice_used=11452,slice_total=11550),
        source_map='frozen room_full map_0; no SLAM rerun; no dense model or RGB point cloud'))
    print('PREPARED',str(output))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.output)
