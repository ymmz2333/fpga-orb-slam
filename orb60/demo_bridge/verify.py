"""One offline software verification entry; does not contact either board."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'orb60/build/demo_bridge'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    checks=[]
    commands=[('native_geometry_and_ownership',[OUT/'native/test-zslam.exe',OUT/'native']),
              ('native_bridge_core',[OUT/'native/test-bridge.exe']),
              ('bridge_integration',[sys.executable,'-m','orb60.demo_bridge.tests.offline_gate']),
              ('desktop_controls',[sys.executable,'-m','unittest','orb60.demo_bridge.tests.test_controls','orb60.demo_bridge.tests.test_export_map','orb60.demo_bridge.tests.test_color','-v'])]
    for name,command in commands:
        start=time.monotonic()
        with (OUT/(name+'.log')).open('w',encoding='utf-8') as f:
            result=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=90)
        checks.append(dict(name=name,returncode=result.returncode,seconds=time.monotonic()-start,log=name+'.log'))
        print(('PASS' if not result.returncode else 'FAIL'),name,flush=True)
        if result.returncode:
            print((OUT/(name+'.log')).read_text(errors='replace')[-6000:])
            break
    upstream=ROOT/'zynq7015_usb_slam_20261024/source'
    frozen=json.loads((ROOT/'zynq7015_demo/UPSTREAM_SHA256.json').read_text())
    originals_unchanged=None
    if upstream.is_dir():
        originals_unchanged=all((upstream/name).is_file() and hashlib.sha256((upstream/name).read_bytes()).hexdigest()==digest for name,digest in frozen.items())
    files=list((ROOT/'orb60/demo_bridge').rglob('*.py'))+list((ROOT/'orb60/demo_bridge/rk').glob('*'))+list((ROOT/'zynq7015_demo/src').glob('*.cpp'))+list((ROOT/'zynq7015_demo/include').rglob('*.hpp'))
    files+=[ROOT/'orb60/viewer/app.py',ROOT/'orb60/viewer/demo_controls.py']
    source_sha={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.is_file() and '__pycache__' not in p.parts}
    report=dict(status='PASS_OFFLINE_SOFTWARE' if len(checks)==4 and all(not c['returncode'] for c in checks) and originals_unchanged is not False else 'FAIL',
                scope='Windows native software and local TCP only; synthetic poses in protocol fixture; historical PL records used only for byte transport',
                checks=checks,upstream_source_files=len(frozen),upstream_unchanged=originals_unchanged,
                source_sha256=source_sha,arm_build='BLOCKED_TOOLCHAIN',rk_build='NOT_RUN',
                board_camera_fpga='NOT_RUN',board_handover_and_disconnected_localization='NOT_RUN',board_reboot='NOT_RUN',
                fps='NOT_MEASURED',localization_accuracy='NOT_MEASURED')
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['status']=='PASS_OFFLINE_SOFTWARE' else 1


if __name__=='__main__':raise SystemExit(main())
