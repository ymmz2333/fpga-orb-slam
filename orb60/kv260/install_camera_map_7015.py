"""Install a sealed map into a fresh native7015 network-localization release.

PS-only transfer and native import/roundtrip; no PL reload or production map
replacement. Recorded-diagnostic installation is a separate explicit component
mode and never asserts that a real camera produced its map.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import tarfile
from orb60.demo_bridge.map_bundle import validate
from .run_network_system import load,digest
from .two_board_session import Board


def require_space(board,additional_bytes=0):
    """Reserve runtime headroom before writes, rather than failing at mktemp."""
    board.run("df -Pk /opt/orb-demo | awk 'NR==2 {print $4}'",'free_space',timeout=15)
    value=(board.output/'free_space.stdout.log').read_text().strip()
    if not re.fullmatch('[0-9]+',value):raise ValueError('7015 free-space measurement missing')
    available=int(value)*1024;required=32*1024*1024+additional_bytes
    if available<required:
        raise RuntimeError('7015存储空间不足：剩余 %.1f MiB，需要至少 %.1f MiB'%(available/2**20,required/2**20))
    return available


def reuse(board,handoff,previous):
    """Verify a previously installed identical map; never clone it on reconnect."""
    proof,transfer,bundle=check_handoff(handoff,allow_camera_diagnostic=True,allow_manual_latest=True)
    c=board.connection;release=previous.get('release','')
    expected=dict(version=bundle['version'],archive_sha256=transfer['sha256'],
                  calibration_sha256=digest(Path(handoff)/'map/camera_orb.csv'),
                  native_sha256=c['network_localizer_sha256'],importer_sha256=c['map_importer_sha256'])
    if (any(previous.get(k)!=v for k,v in expected.items()) or
        not re.fullmatch('/opt/orb-demo/kv260_network_camera_[A-Za-z0-9_]+',release) or
        not re.fullmatch('[a-f0-9]{64}',previous.get('manifest_sha256',''))):return None
    require_space(board)
    q=shlex.quote
    script=f'''set -eu
if test ! -d {q(release)}; then echo MAP_RELEASE_MISSING; exit 0; fi
test "$(readlink -f {q(release)})" = {q(release)}
cd {q(release)}
test "$(sha256sum SHA256SUMS | cut -d ' ' -f 1)" = {q(previous['manifest_sha256'])}
sha256sum -c SHA256SUMS >/dev/null
test "$(head -n 1 maps_live/current)" = {q(bundle['version'])}
test "$(sha256sum camera_live.csv | cut -d ' ' -f 1)" = {q(expected['calibration_sha256'])}
test "$(sha256sum bin/zynq-demo | cut -d ' ' -f 1)" = {q(expected['native_sha256'])}
test "$(sha256sum bin/zynq-map-install | cut -d ' ' -f 1)" = {q(expected['importer_sha256'])}
cmp maps_live/versions/{bundle['version']}/map.zmap maps_live/versions/{bundle['version']}/roundtrip.zmap
echo INSTALLED_MAP_REUSE_VERIFIED
'''
    board.run(script,'reuse_map',timeout=90)
    marker=(board.output/'reuse_map.stdout.log').read_text().strip()
    if marker=='MAP_RELEASE_MISSING':return None
    if marker!='INSTALLED_MAP_REUSE_VERIFIED':raise ValueError('No verified installed-map reuse receipt')
    return dict(previous,status='ACTUAL_NATIVE_7015_REUSED_MAP_RELEASE_VERIFIED',reuse_verified=True,
                original_install_status=previous.get('original_install_status',previous['status']))


def check_handoff(handoff,mode='live_camera',allow_camera_diagnostic=False,allow_manual_latest=False):
    handoff=Path(handoff);proof=load(handoff/'HANDOFF.json');transfer=load(handoff/'TRANSFER.json')
    if mode not in ('live_camera','recorded_diagnostic'):raise ValueError('Explicit camera or diagnostic input mode required')
    formats=['KV260_LIVE_CAMERA_SOURCE_V1']
    if allow_camera_diagnostic:formats.append('KV260_LIVE_CAMERA_DIAGNOSTIC_SOURCE_V1')
    if allow_manual_latest:formats.append('KV260_MANUAL_LATEST_MAP_SOURCE_V1')
    if proof['source'].get('format')=='KV260_MANUAL_LATEST_MAP_SOURCE_V1' and (
        not proof['source'].get('manual_control') or proof['source'].get('single_map_required') is not False or
        proof['source'].get('map_selection')!='Atlas current map at completed shutdown'):
        raise ValueError('Latest-map handoff lacks explicit manual current-map selection')
    if mode=='live_camera' and proof['source'].get('format') not in formats:
        raise ValueError('A live-camera installation requires accepted real-camera source evidence')
    camera=handoff/'map/camera_orb.csv';bundle=validate(handoff/'map',camera.read_bytes())
    if mode=='live_camera' and proof['source'].get('camera_sha256')!=digest(camera):
        raise ValueError('Live-camera source and installed map calibration differ')
    if (proof.get('format')!='KV260_TO_7015_MAP_V1' or proof['dense_display_points']<1 or
        bundle!=proof['map'] or bundle['version']!=transfer['expected_map_version'] or
        digest(handoff/'MAPPING_RESULT.json')!=proof['source']['result_sha256']):
        raise ValueError('Sealed colored map/source identity mismatch')
    from orb60.demo_bridge.dense_environment import validate as dense_count
    if dense_count(handoff/'map/dense_environment.bin',handoff/'map/points.csv',camera)!=proof['dense_display_points']:
        raise ValueError('Dense environment count differs from handoff receipt')
    archive=handoff/'map_7015.tar.gz'
    if archive.is_symlink() or archive.stat().st_size>64*1024*1024 or digest(archive)!=transfer['sha256']:
        raise ValueError('Map archive identity/capacity mismatch')
    expected={f'map/{p.name}':p for p in (handoff/'map').iterdir() if p.is_file()}
    seen=set();total=0
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name not in expected or member.name in seen or member.size>32*1024*1024:
                raise ValueError('Unexpected/nonregular map archive member')
            total+=member.size
            if total>64*1024*1024 or member.size!=expected[member.name].stat().st_size:
                raise ValueError('Oversized or changed map archive member')
            with tar.extractfile(member) as f:
                import hashlib
                if hashlib.sha256(f.read()).hexdigest()!=digest(expected[member.name]):raise ValueError('Archived map bytes differ')
            seen.add(member.name)
    if seen!=set(expected):raise ValueError('Map archive is incomplete')
    return proof,transfer,bundle


def install(board,handoff,release,mode='live_camera',allow_camera_diagnostic=False,allow_manual_latest=False):
    proof,transfer,bundle=check_handoff(handoff,mode,allow_camera_diagnostic,allow_manual_latest);handoff=Path(handoff)
    if not re.fullmatch('/opt/orb-demo/kv260_network_camera_[a-zA-Z0-9_]+',release):
        raise ValueError('Fresh isolated native camera release required')
    c=board.connection
    for key in ('network_localization_template','localization_template'):
        if not re.fullmatch('/opt/orb-demo/[a-zA-Z0-9_-]+',c[key]):raise ValueError('Invalid template path')
    for key in ('network_localizer_sha256','map_importer_sha256'):
        if not re.fullmatch('[a-f0-9]{64}',c[key]):raise ValueError('Pinned native product identity required')
    unpacked=sum(p.stat().st_size for p in (handoff/'map').iterdir() if p.is_file())
    require_space(board,3*unpacked+(handoff/'map_7015.tar.gz').stat().st_size+16*1024*1024)
    quoted={key:shlex.quote(value) for key,value in dict(RELEASE=release,TEMPLATE=c['network_localization_template'],
            IMPORTER=c['localization_template']+'/bin/zynq-map-install',APP_SHA=c['network_localizer_sha256'],
            IMPORT_SHA=c['map_importer_sha256'],ARCHIVE_SHA=transfer['sha256'],VERSION=bundle['version'],
            MODE=mode,CAMERA='camera_live.csv' if mode=='live_camera' else 'camera_recorded.csv',
            MAPS='maps_live' if mode=='live_camera' else 'maps_recorded').items()}
    script='''set -eu
test ! -e /run/orb-demo.lock
test ! -e @RELEASE@
(cd @TEMPLATE@ && sha256sum -c SHA256SUMS >/dev/null)
grep -q '^ALL_TESTS_PASS ' @TEMPLATE@/selftests/unit.log
test "$(sha256sum @TEMPLATE@/bin/zynq-demo | cut -d ' ' -f 1)" = @APP_SHA@
test "$(sha256sum @IMPORTER@ | cut -d ' ' -f 1)" = @IMPORT_SHA@
mkdir @RELEASE@
cat >@RELEASE@/map.tar.gz
cd @RELEASE@
test "$(sha256sum map.tar.gz | cut -d ' ' -f 1)" = @ARCHIVE_SHA@
tar -xzf map.tar.gz
mkdir bin
cp @TEMPLATE@/bin/zynq-demo bin/
cp @IMPORTER@ bin/
cp @TEMPLATE@/run_network_camera_localization.sh .
cp map/camera_orb.csv @CAMERA@
printf '%s\n' @MODE@ >INPUT_MODE
bin/zynq-map-install @MAPS@ @CAMERA@ map @VERSION@
test "$(head -n 1 @MAPS@/current)" = @VERSION@
cmp @MAPS@/versions/@VERSION@/map.zmap @MAPS@/versions/@VERSION@/roundtrip.zmap
find bin map @MAPS@ -type f | sort | xargs sha256sum >SHA256SUMS
sha256sum @CAMERA@ INPUT_MODE run_network_camera_localization.sh >>SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null
sync
printf 'NATIVE_CAMERA_MAP_IMPORT_ROUNDTRIP_PASS %s\n' @VERSION@
sha256sum SHA256SUMS
'''
    for key,value in quoted.items():script=script.replace('@'+key+'@',value)
    with (handoff/'map_7015.tar.gz').open('rb') as body:board.run(script,'install_camera_map',timeout=300,stdin=body)
    matches=re.findall(r'^([a-f0-9]{64})  SHA256SUMS$',(board.output/'install_camera_map.stdout.log').read_text(),re.M)
    if len(matches)!=1:raise ValueError('Missing installed-map manifest identity')
    return dict(status='ACTUAL_NATIVE_7015_NETWORK_MAP_IMPORT_ROUNDTRIP_PASS',release=release,input_mode=mode,
                version=bundle['version'],dense_points=proof['dense_display_points'],archive_sha256=transfer['sha256'],
                manifest_sha256=matches[0],native_sha256=c['network_localizer_sha256'],importer_sha256=c['map_importer_sha256'],
                calibration_sha256=digest(handoff/'map/camera_orb.csv'),source=proof['source'],
                diagnostic_only=proof['source'].get('diagnostic_only',False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','connection','handoff','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--release',required=True);p.add_argument('--recorded-diagnostic',action='store_true')
    p.add_argument('--allow-camera-diagnostic',action='store_true',help='Explicit camera downstream experiment; not stability acceptance');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);b=Board(a.root.resolve(),load(a.connection),a.output)
    state=dict(status='RUNNING',source_input='recorded_diagnostic' if a.recorded_diagnostic else 'live_camera')
    try:state=install(b,a.handoff,a.release,state['source_input'],a.allow_camera_diagnostic)
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(a.output/'RESULT.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)
