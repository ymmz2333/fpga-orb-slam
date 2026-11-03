"""Install a separate PS-only release and run its ARM geometry self-test."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import tarfile
from orb60.kv260.two_board_session import Board


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(root,connection,build,source,live_camera,protocol,release,output,manual_protocol=None):
    root,build,source,output=map(lambda p:Path(p).resolve(),(root,build,source,output))
    if not re.fullmatch('/opt/orb-demo/kv260_network_camera_[a-zA-Z0-9_]+',release):raise ValueError('Isolated7015 release path required')
    b=json.loads((build/'BUILD.json').read_text());gate=json.loads((Path(protocol)/'RESULT.json').read_text())
    if b['status']!='ARM_NETWORK_CAMERA_PS_BUILD_PASS' or gate['status']!='NATIVE_NETWORK_CAMERA_PROTOCOL_GATE_PASS' or gate['binary_sha256']!=b['products_sha256']['test_network_camera_host']:
        raise ValueError('Completed native protocol and cross-build gates required')
    if manual_protocol:
        manual=json.loads((Path(manual_protocol)/'RESULT.json').read_text())
        if manual['status']!='NATIVE_MANUAL_NETWORK_PROTOCOL_GATE_PASS' or manual['binary_sha256']!=b['products_sha256']['test_network_camera_host']:
            raise ValueError('Matching explicit manual-end protocol gate required')
    for name,h in b['products_sha256'].items():
        if sha(build/'bin'/name)!=h:raise ValueError('ARM product changed')
    output.mkdir(parents=True,exist_ok=False);c=json.loads(Path(connection).read_text());board=Board(root,c,output)
    recorded_camera=output/'camera_recorded.csv'
    with recorded_camera.open('wb') as f:
        board.run('cat '+shlex.quote(c['localization_template']+'/map/camera_orb.csv'),'recorded_calibration',stdout=f)
    importer=output/'zynq-map-install'
    with importer.open('wb') as f:board.run('cat '+shlex.quote(c['localization_template']+'/bin/zynq-map-install'),'retained_importer',stdout=f)
    if sha(importer)!=c.get('map_importer_sha256','a6271c2211ed765fc06b43fec7436f5ea9913a2f28c1831caecdfa7c6f0d5e4f'):
        raise ValueError('Retained native map importer changed')
    files={name:build/'bin'/name.split('/')[-1] for name in ('bin/zynq-demo','bin/test-zslam')}
    files['camera_live.csv']=Path(live_camera)
    files['camera_recorded.csv']=recorded_camera
    files['run_network_camera_localization.sh']=Path(__file__).with_name('run_network_camera_localization.sh')
    files['run_recording_localization.sh']=Path(__file__).with_name('run_recording_localization.sh')
    files['README_ZH.md']=Path(__file__).with_name('README_ZH.md')
    files['bin/zynq-map-install']=importer
    for p in (source/'zynq7015_demo/tests/fixtures').rglob('*'):
        if p.is_file():files['bin/test-fixtures/'+p.relative_to(source/'zynq7015_demo/tests/fixtures').as_posix()]=p
    checks=''.join(sha(p)+'  '+name+'\n' for name,p in files.items()).encode()
    payload=output/'payload.tar.gz'
    with tarfile.open(payload,'w:gz') as tar:
        for name,p in files.items():tar.add(p,arcname=name)
        info=tarfile.TarInfo('SHA256SUMS');info.size=len(checks);tar.addfile(info,io.BytesIO(checks))
    old=shlex.quote(c['localization_template']);target=shlex.quote(release)
    script='''set -eu
test ! -e /run/orb-demo.lock
test ! -e TARGET
mkdir TARGET
tar -xzf - -C TARGET
cd TARGET
chmod 755 bin/zynq-demo bin/test-zslam bin/zynq-map-install run_network_camera_localization.sh run_recording_localization.sh
sha256sum -c SHA256SUMS > install_sha.log
cp -r OLD/maps maps_recorded
mkdir selftests
bin/test-zslam selftests >selftests/unit.log 2>&1
grep -q '^ALL_TESTS_PASS ' selftests/unit.log
cat /proc/sys/kernel/random/boot_id > installed_boot.txt
printf 'NETWORK_CAMERA_RELEASE_INSTALLED=TARGET\n'
tail -n 3 selftests/unit.log
'''.replace('TARGET',target).replace('OLD',old)
    state=dict(status='INSTALLING',release=release,payload_sha256=sha(payload),products=b['products_sha256'],hardware_programmed=False,manual_protocol_verified=manual_protocol is not None)
    try:
        with payload.open('rb') as f:board.run(script,'install',timeout=300,stdin=f)
        state['status']='SEPARATE_NETWORK_CAMERA_RELEASE_AND_ARM_SELFTEST_PASS'
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'RESULT.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','connection','build','source','live-camera','protocol','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--manual-protocol',type=Path)
    p.add_argument('--release',required=True);run(**vars(p.parse_args()))
