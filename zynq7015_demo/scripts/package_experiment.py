"""Bundle checked PS-only candidates without changing board SD hardware."""
from pathlib import Path
import argparse,datetime,hashlib,json,shutil,tarfile
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--arm',type=Path,required=True);p.add_argument('--stage',required=True);a=p.parse_args()
assert a.stage.replace('_','').isalnum()
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
arm=a.arm.resolve();sw=json.loads((arm/'checks.json').read_text());native=json.loads((root/'build/native/checks.json').read_text())
assert sw['status']==native['status']=='PASS'
assert native.get('tests_run',True), 'Native build-only is not a test PASS'
for name,h in native.get('input_sha256',{}).items():assert digest(root/name)==h,name
for name,h in sw['input_sha256'].items():assert digest(root/name)==h,name
for name,meta in sw['binaries'].items():assert digest(arm/name)==meta['sha256'],name
out=root/'output'/('slam60_'+a.stage+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
for name in ['bin','scripts','config','evidence']:(out/name).mkdir(parents=True,exist_ok=False)
for name in sw['binaries']:shutil.copy2(arm/name,out/'bin'/name)
shutil.copytree(root/'tests/fixtures/camera',out/'bin/test-fixtures/camera')
shutil.copy2(root/'config/camera_handoff.csv',out/'config/camera_handoff.csv')
shutil.copy2(arm/'checks.json',out/'evidence/arm_build.json')
shutil.copy2(root/'build/native/checks.json',out/'evidence/native_checks.json')
shutil.copy2(root/('USB_CAMERA_30FPS_ZH.md' if a.stage=='camera' else 'OPTIMIZATION_60FPS_ZH.md'),out/'README_ZH.md')
(out/'licenses').mkdir();shutil.copy2(root/'vendor/opencv_p3p/LICENSE',out/'licenses/OpenCV-4.2.0-BSD.txt')
for name in ['LICENSE.md','README.ijg']:
    if (root/'vendor/jpeg_turbo/upstream'/name).is_file():shutil.copy2(root/'vendor/jpeg_turbo/upstream'/name,out/'licenses'/('libjpeg-turbo-'+name))
for source,name in [('src/spng/LICENSE','libspng-LICENSE'),('src/spng/libpng-LICENSE.txt','libpng-LICENSE.txt'),('src/spng/zlib/LICENSE','zlib-LICENSE')]:
    shutil.copy2(root/'vendor/jpeg_turbo/upstream'/source,out/'licenses'/name)
(out/'licenses/JPEG-NOTICE.txt').write_text('This software is based in part on the work of the Independent JPEG Group.\n',encoding='ascii')
if (root/'USB_CAMERA_30FPS_ZH.md').is_file():shutil.copy2(root/'USB_CAMERA_30FPS_ZH.md',out/'USB_CAMERA_30FPS_ZH.md')
for name in ['bench_poll.sh','bench_render.sh','bench_buffers.sh','bench_continuous.sh','bench_decode.sh','bench_trajectory.sh','bench_retrieval.sh','bench_usb_camera.sh','bench_camera_region.sh','bench_focus_preview.sh']:
    if (root/'scripts'/name).is_file():(out/'scripts'/name).write_text((root/'scripts'/name).read_text(),encoding='utf-8',newline='\n')
with tarfile.open(out/'source.tar.gz','w:gz') as tar:
    for name in ['src','include','rtl','scripts','tests','tools','config','interfaces','cmake','vendor','CMakeLists.txt','AGENTS.md','OPTIMIZATION_60FPS_ZH.md','USB_CAMERA_30FPS_ZH.md','LICENSE']:
        tar.add(root/name,arcname='source/'+name,filter=lambda info:None if '__pycache__' in info.name or info.name.endswith('.pyc') else info)
(out/'manifest.json').write_text(json.dumps(dict(scope='PS software experiment only; no SD/PL replacement',stage=a.stage,arm=str(arm),hardware_release='sd_ssh_20261024_001751',board_execution='NOT_RUN'),indent=2)+'\n',encoding='utf-8')
(out/'SHA256SUMS').write_text(''.join(digest(f)+'  '+f.relative_to(out).as_posix()+'\n' for f in sorted(out.rglob('*')) if f.is_file()),encoding='ascii',newline='\n')
archive=out.with_suffix('.tar.gz')
with tarfile.open(archive,'w:gz') as tar:tar.add(out,arcname=out.name)
(archive.with_suffix('.json')).write_text(json.dumps(dict(status='PASS',archive=str(archive),sha256=digest(archive),bytes=archive.stat().st_size),indent=2)+'\n')
print(json.dumps(dict(status='PASS',package=str(out),archive=str(archive),sha256=digest(archive)),indent=2),flush=True)
