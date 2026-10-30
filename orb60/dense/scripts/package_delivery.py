"""Package authored implementation, private NPU runtime/model and measurements."""
import hashlib
import json
from pathlib import Path
import zipfile
import argparse


def main():
    project=Path(__file__).resolve().parents[3]
    build=project/'orb60/build/dense'
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    target=args.output or build/'orb60_dense_implementation.zip'
    target.parent.mkdir(parents=True,exist_ok=True)
    files={}
    for folder in ['orb60/dense','orb60/viewer']:
        for path in (project/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py','.cpp','.h','.txt','.md','.ps1','.sh'}:
                files[str(path.relative_to(project)).replace('\\','/')]=path
    files['Launch-ORB-Dense.cmd']=project/'Launch-ORB-Dense.cmd'
    files['Launch-ORB-Dense-Result.cmd']=project/'Launch-ORB-Dense-Result.cmd'
    files['orb60/scripts/run_slam_network.py']=project/'orb60/scripts/run_slam_network.py'
    files['orb60/linux/client.py']=project/'orb60/linux/client.py'
    extras={
        'models/depth.rknn':'midas-small-fp16/depth.rknn',
        'models/private_rknn/librknnrt.so':'assets/librknnrt.so',
        'models/private_rknn/rknn_api.h':'assets/rknn_api.h',
        'models/assets.json':'assets/assets.json',
        'models/midas-assets.json':'assets/midas-assets.json',
        'models/conversion-environment.txt':'assets/conversion-environment.txt',
        'models/npu_acceptance.json':'midas-small-fp16/acceptance.json',
        'models/operator-profile.txt':'midas-small-fp16/board/operator-profile.txt',
        'models/rejected_da2_numerical.json':'da2-small-fp16/board/numerical-gate.json',
        'evidence/full_state.json':'room_full/state.json',
        'evidence/full_result.json':'room_full/result.json',
        'evidence/full_artifact_acceptance.json':'room_full/artifact_acceptance.json',
        'evidence/full_viewer_acceptance.json':'room_full/viewer/acceptance.json',
        'evidence/short_artifact_acceptance.json':'room900_final/artifact_acceptance.json',
        'evidence/pc_decoder_comparison.json':'room900_final/pc_decoder_comparison.json',
        'evidence/video_preparation_acceptance.json':'video_preparation_acceptance.json'}
    files.update({name:build/relative for name,relative in extras.items()})
    for name in ['result.json','refinement_acceptance.json','provenance.json','decoder_acceptance.json','viewer_playback/acceptance.json','viewer_playback/normal_loop_metrics.json']:
        path=build/'room_full_detail'/name
        if path.is_file():files['evidence/detail/'+name]=path
    for path in (build/'room_full_detail/source_used').glob('*.py'):
        files['evidence/detail/source_used/'+path.name]=path
    for name in ['acceptance.json','desktop_metrics.json','live_report.json','tracking_status.json','npu_worker.json','operator-profile.txt','build_acceptance.json']:
        path=build/'live_incremental_900_30fps'/name
        if path.is_file():files['evidence/live/'+name]=path
    latest=build/'live_full_evidence.local.json'
    if latest.is_file():
        folder=build/json.loads(latest.read_text(encoding='utf-8-sig'))['directory']
        for name in ['live_acceptance.json','desktop_metrics.json','live_report.json','tracking_status.json','npu_worker.json','operator-profile.txt',
                     'fpga_preflight.json','input_acceptance.json','input_repair_acceptance.json']:
            if (folder/name).is_file():files['evidence/live_full/'+name]=folder/name
    for directory in ('controls_qa','controls_restart_v2'):
        for path in (build/directory).glob('*.json'):
            files['evidence/'+directory+'/'+path.name]=path
    for folder in build.glob('live_20261022_04*'):
        if (folder/'failure_acceptance.json').is_file():
            files['evidence/failure/'+folder.name+'.json']=folder/'failure_acceptance.json'
    for folder,label in [('midas-v21','MiDaS'),('gen-efficientnet','EfficientNet'),('depth-anything-v2','DepthAnything')]:
        license=build/'assets'/folder/'LICENSE'
        if license.is_file():files['licenses/'+label+'-LICENSE.txt']=license
    manifest={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items()}
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name,path in files.items():archive.write(path,name)
        archive.writestr('SHA256.json',json.dumps(manifest,indent=2)+'\n')
    h=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
    print(json.dumps(dict(file=str(target),bytes=target.stat().st_size,sha256=h,files=len(files)),indent=2))
    (build/'implementation_archive.json').write_text(json.dumps(dict(sha256=h,files=manifest),indent=2)+'\n')


if __name__=='__main__':main()
