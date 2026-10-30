"""Assemble authored helpers around frozen evidence, then inventory without credentials."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil
from common import load,save,sha

SOURCE=Path(__file__).resolve().parent

def authored(source,target,lf=False):
    target.parent.mkdir(parents=True,exist_ok=True)
    data=source.read_bytes()
    if lf:data=data.replace(b'\r\n',b'\n')
    target.write_bytes(data)

def assemble(root):
    for name in ('common.py','build_map.py','collect.py','localize.py','compare.py','verify.py','check_cpp.py',
                 'export_inputs.py','render.py','test_handoff.py','build_hardware.ps1','write_bitstream.tcl','build_reference.sh'):
        authored(SOURCE/name,root/'tools'/name,lf=name.endswith('.sh'))
    for name in ('reference.c','reference.h','test_reference.c','ps_direct_example.c','fixed_pnp.cpp'):
        authored(SOURCE/name,root/'reference'/name)
    authored(SOURCE/'environment_template.ps1',root/'scripts/project_env.ps1')
    authored(SOURCE/'README_ZH.md',root/'README.md')
    (root/'requirements.txt').write_bytes(b'numpy==2.5.2\nopencv-python==5.0.0.93\nmatplotlib==3.11.2\nav==18.1.0\n')
    license_root=root/'LICENSES';license_root.mkdir(exist_ok=True)
    shared=root/'fpga_baseline/layer2/inputs/FPGA_ORB_SHARED_v1.0'
    authored(shared/'LICENSE',license_root/'GPL-3.0.txt')
    authored(shared/'NOTICE.md',license_root/'UPSTREAM_NOTICE.md')
    notice='''The derived ORB source/reference package retains GPL-3.0-or-later and its upstream notices.
New handoff helpers are provided under GPL-3.0-or-later. See GPL-3.0.txt.
constants.hpp in each frozen snapshot retains University of Zaragoza and Willow Garage notices.
AMD packaged IP/tool files retain their original notices; AMD tools are not redistributed.
OpenCV/NumPy/PyAV/Matplotlib are external dependencies, not bundled runtimes.
Original project video and generated map are included as project handoff test data.
No dense models, credentials, SSH private keys or machine-local board configuration are included.
'''
    (license_root/'README.txt').write_bytes(notice.encode('ascii'))
    accept=load(root/'golden/capture_acceptance.json');map_accept=load(root/'map/map_acceptance.json')
    cpp=load(root/'reports/cpp_fixed_pnp.json');localization=load(root/'localization_reference/run_report.json')
    if accept['status']!='PASS' or map_accept['status']!='PASS' or cpp['status']!='PASS':raise ValueError('Missing stage acceptance')
    save(root/'delivery.json',dict(format_version=1,status='ASSEMBLED_PENDING_FINAL_OFFLINE_VALIDATION',
        assembled_utc=datetime.now(timezone.utc).isoformat(),geometry=[960,720,8],device='xc7z015clg485-2',clock_mhz=150,
        physical_frames=accept['frames'],physical_records=accept['records'],map_points=map_accept['points'],
        map_keyframes=map_accept['keyframes'],map_observations=map_accept['observations'],
        reference_localization_valid=localization['valid'],original_slam_valid=map_accept['slam_reference_valid'],
        unchanged_world_scale=True,cpu_orb_calls=0,board_required_for_offline_validation=False,
        excluded=['dense/RGB cloud','camera integration','HDMI integration','finished Zynq PS localization application']))
    inventory(root)

def inventory(root):
    files=[p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='SHA256SUMS']
    forbidden=('.pem','.key','.pyc')
    for path in files:
        if path.suffix.lower() in forbidden or path.name in ('local_env.ps1','board.local.json','board_ssh.json','local_board.json'):
            raise ValueError('Private/generated file in bundle: '+str(path))
    (root/'SHA256SUMS').write_bytes(''.join(sha(p)+'  '+p.relative_to(root).as_posix()+'\n'
        for p in sorted(files)).encode('ascii'))
    print('INVENTORY',len(files),'files',sum(p.stat().st_size for p in files),'bytes')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--inventory-only',action='store_true')
    a=p.parse_args();inventory(a.bundle) if a.inventory_only else assemble(a.bundle)
