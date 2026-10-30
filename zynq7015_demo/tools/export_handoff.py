"""Export current source and verified dependencies without compiling or touching a board."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import shutil
import tarfile
import zipfile
from verify_handoff import verify

ROOT = Path(__file__).resolve().parents[1]
PLD = ROOT.parent
ARM = ROOT / 'build/arm_20261024_180124'
S1 = ROOT / 'build/s1_controls_20261024_192801'
UVC = ROOT / 'build/uvc_20261024_162629'
SYNTH = PLD / '.work/z18/20261023_194328'
ROUTE = SYNTH / 'route_20261023_195215'
FINAL = SYNTH / 'final_20261023_201146'
RETAINED_NAME = 'zynq7015_localization_handoff_20261022/zynq7015_localization_handoff_20261022'
RETAINED = PLD / RETAINED_NAME
BASELINE = PLD / 'baselines/zynq_slam_30fps_20261024_003206'
FACTORY = Path('C:/baidunetdiskdownload/ACZ7015_最核心学习资料_按顺序/06_Linux_PetaLinux_驱动/07_Linux源码/ACZ7015出厂工程和Linux源码/ACZ7015_Linux_Factory_Source.tar.gz')


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def source_path(name):
    return ROOT.joinpath(*name.replace('\\', '/').split('/'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or ROOT == out or ROOT in out.parents:
        raise ValueError('Use a NEW output directory outside the active source repository')
    out.mkdir(parents=True)
    bindings = []

    def copy(source, relative):
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError('Missing or linked source: ' + str(source))
        destination = out / relative
        if destination.exists():
            if sha(destination) != sha(source):
                raise ValueError('Conflicting destination: ' + str(relative))
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def tree(source, relative):
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Linked directory/file not supported: ' + str(path))
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                copy(path, Path(relative) / path.relative_to(source))

    def bind(path, expected, relative, role):
        if sha(path) != expected:
            raise ValueError('Existing evidence/source mismatch: ' + str(path))
        if sha(out / relative) != expected:
            raise ValueError('Copied binding mismatch: ' + str(relative))
        bindings.append(dict(role=role, package_path=Path(relative).as_posix(), sha256=expected))

    print('SOURCE: copying current authored files and frozen vendor sources', flush=True)
    for name in ['src', 'include', 'rtl', 'tests', 'scripts', 'tools', 'config', 'interfaces', 'cmake', 'vendor', 'handoff_docs']:
        tree(ROOT / name, Path('source') / name)
    for path in sorted(ROOT.iterdir()):
        if path.is_file() and (path.suffix == '.md' or path.name in ['CMakeLists.txt', 'LICENSE', '.gitignore']):
            copy(path, Path('source') / path.name)
    copy(ROOT / 'tools/verify_handoff.py', 'verify_handoff.py')
    copy(ROOT / 'handoff_docs/README_ZH.md', 'README_ZH.md')
    for name in ['SOURCE_MAP_ZH.md', 'BUILD_AND_VERIFY_ZH.md', 'BOARD_HANDOVER_ZH.md', 'STATUS_AND_NEXT_ZH.md']:
        copy(ROOT / 'handoff_docs' / name, Path('docs') / name)

    arm, native, s1 = read(ARM / 'checks.json'), read(ROOT / 'build/native/checks.json'), read(S1 / 'checks.json')
    if any(report['status'] != 'PASS' for report in [arm, native, s1]) or not native.get('tests_run'):
        raise ValueError('Verified build reports no longer PASS')
    for report in [arm, native]:
        jpeg = Path(report['jpeg_dependency'])
        for name in ['checks.json', 'libturbojpeg.a', 'build.log', 'configure.log']:
            copy(jpeg.parent / name, Path('source/build') / jpeg.parent.name / name)
        meta = read(jpeg)
        if meta['status'] != 'PASS':
            raise ValueError('JPEG static library report no longer PASS')
        bind(jpeg.parent / 'libturbojpeg.a', meta['library_sha256'],
             Path('source/build') / jpeg.parent.name / 'libturbojpeg.a', 'jpeg_static_library')
    for role, report in [('arm_input', arm), ('native_input', native)]:
        for name, expected in report['input_sha256'].items():
            relative = Path('source') / name.replace('\\', '/')
            bind(source_path(name), expected, relative, role)
    for path in (ROOT / 'build/native').glob('*'):
        if path.is_file() and path.suffix in ['.json', '.log']:
            copy(path, Path('source/build/native') / path.name)
    for build in [ARM, S1, UVC]:
        for path in build.iterdir():
            if path.is_file() and path.suffix in ['.json', '.log', '.rsp', '.cmd', '.c']:
                copy(path, Path('evidence/builds') / build.name / path.name)

    print('ARTIFACTS: checking source, ARM helpers, matched UVC and final routed hardware', flush=True)
    tree(ROOT / 'output/slam60_camera_20261024_180726', 'artifacts/camera_runtime')
    tree(S1 / 'payload', 'artifacts/camera_runtime')
    tree(ROOT / 'output/calibration_q12_03_checked_20261024_1840', 'artifacts/camera_runtime/q12_calibration')
    for name, meta in arm['binaries'].items():
        bind(ARM / name, meta['sha256'], Path('artifacts/camera_runtime/bin') / name, 'arm_binary')
    for name, expected in s1['sources'].items():
        bind(ROOT / 'tools' / name, expected, Path('source/tools') / name, 's1_input')
    for name, expected in s1['binaries'].items():
        bind(S1 / name, expected, Path('artifacts/camera_runtime/s1-controls') / name, 's1_binary')
    if sha(out / 'artifacts/camera_runtime/run_camera_s1.sh') != sha(ROOT / 'scripts/run_camera_s1.sh'):
        raise ValueError('S1 controller differs from deployed payload')
    runtime = out / 'artifacts/camera_runtime'
    (runtime / 'HANDOFF_SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.relative_to(runtime).as_posix() + '\n'
        for p in sorted(runtime.rglob('*')) if p.is_file()), encoding='ascii', newline='\n')

    crc = read(UVC / 'import_crc_verification.json')
    for name, meta in crc['modules'].items():
        copy(UVC / (name + '.ko'), 'artifacts/uvc/' + name + '.ko')
        bind(UVC / (name + '.ko'), meta['sha256'], 'artifacts/uvc/' + name + '.ko', 'uvc_module')
        if not meta['all_import_crcs_match']:
            raise ValueError('UVC import CRC verification is not PASS')
    copy(UVC / 'import_crc_verification.json', 'artifacts/uvc/import_crc_verification.json')
    copy(ROOT / 'build/camera_kernel_4_14_factory/.config', 'artifacts/uvc/live.config')
    copy(ROOT / 'build/camera_kernel_4_14_factory/Module.symvers', 'artifacts/uvc/Module.symvers')
    copy(ROOT / 'build/camera_kernel_4_14_factory/uvc_extraction_manifest.json', 'artifacts/uvc/source_extraction_manifest.json')
    hw, synth = read(FINAL / 'status.json'), read(SYNTH / 'status.json')
    if hw['status'] != 'PASS' or read(ROUTE / 'review.json')['status'] != 'PASS':
        raise ValueError('Hardware export/review not PASS')
    for name in ['s_wrapper.bit', 's_wrapper.hdf', 's_wrapper.hwdef', 's_wrapper.sysdef', 'status.json', 'source_route_review.json', 'bit_drc.rpt', 'finalize.tcl']:
        copy(FINAL / name, Path('artifacts/fpga/export') / name)
    for name, meta in hw['artifacts'].items():
        bind(FINAL / name, meta['sha256'], Path('artifacts/fpga/export') / name, 'fpga_artifact')
    copy(ROUTE / 's_wrapper_routed.dcp', 'artifacts/fpga/route/s_wrapper_routed.dcp')
    bind(ROUTE / 's_wrapper_routed.dcp', hw['source_checkpoint_sha256'], 'artifacts/fpga/route/s_wrapper_routed.dcp', 'fpga_routed_dcp')
    for p in ROUTE.iterdir():
        if p.is_file() and p.suffix in ['.rpt', '.json', '.md', '.tcl']:
            copy(p, Path('artifacts/fpga/route') / p.name)
    for name in ['status.json', 'contract_check.json', 'staged_ip_hashes.json']:
        copy(SYNTH / name, Path('evidence/fpga_synthesis') / name)
    tree(SYNTH / 'inputs', 'evidence/fpga_synthesis/inputs')
    for name, expected in synth['video_inputs_sha256'].items():
        bind(ROOT / 'rtl/video' / name, expected, 'source/rtl/video/' + name, 'rtl_input')
    for relative, expected in synth['input_hashes'].items():
        copy(RETAINED / relative, Path(RETAINED_NAME) / relative)
        bind(RETAINED / relative, expected, Path(RETAINED_NAME) / relative, 'retained_ip_tcl')
    for name in ['reference/ps_writecombine', 'reference/ps']:
        tree(RETAINED / name, Path(RETAINED_NAME) / name)
    tree(PLD / 'zynq_slam/output/dt_hdmi_20261023', 'source/output/dt_hdmi_20261023')
    # Keep the exact old release and original SD backup for recovery, never overwrite them.
    for name in ['sd_ssh_20261024_001751.tar.gz', 'zslam-sd-original-20261023.tar.gz', 'handoff_map_20261023.tar.gz']:
        copy(BASELINE / 'artifacts' / name, Path('artifacts/recovery') / name)
    copy(BASELINE / 'manifest.json', 'artifacts/recovery/frozen_baseline_manifest.json')
    copy(BASELINE / 'RESTORE_ZH.md', 'artifacts/recovery/HISTORICAL_RESTORE_ZH.md')
    # Runtime firmware container/DT/WC module are copied from the unmodified release.
    for name in ['s_wrapper.bit.bin', 'bitstream.bif', 'bootgen.log']:
        copy(PLD / 'zynq_slam/output/sd_ssh_20261024_001751/firmware' / name, 'artifacts/fpga/firmware/' + name)
    tree(PLD / 'zynq_slam/output/sd_ssh_20261024_001751/hardware', 'artifacts/fpga/sd_hardware')
    with tarfile.open(BASELINE / 'artifacts/sd_ssh_20261024_001751.tar.gz') as archive:
        for path in sorted((out / 'artifacts/fpga/firmware').iterdir()) + sorted((out / 'artifacts/fpga/sd_hardware').iterdir()):
            folder = 'firmware' if path.parent.name == 'firmware' else 'hardware'
            name = 'sd_ssh_20261024_001751/' + folder + '/' + path.name
            data = archive.extractfile(name).read()
            if sha(path) != hashlib.sha256(data).hexdigest():
                raise ValueError('SD runtime hardware differs from frozen recovery archive: ' + name)

    print('EVIDENCE: preserving actual-camera, calibration, S1 and regression records', flush=True)
    evidence = ['usb-live-evidence_20261024_180726.tar.gz', 'affinity-auto-evidence.tar.gz',
                'camera-s1-reset-evidence.tar', 'calibration-q12-03-evidence_20261024_180726.tar.gz',
                'focus-acceptance-evidence_20261024_180726.tar.gz',
                'camera_s1_checked_sources_20261024_195832.tar.json',
                'calibration_q12_detector_tests_20261024_1838.log']
    for name in evidence:
        copy(ROOT / 'output' / name, Path('evidence/archives') / name)
    copy(ROOT / 'output/latest_checkpoint.json', 'evidence/HISTORICAL_checkpoint_20261024_195832.json')
    for name in ['live/usb_live_summary.json', 'raw-regression/analysis.json']:
        copy(ROOT / 'output/usb-live-evidence_20261024_180726' / name, Path('evidence/summary/first_live') / name)
    copy(ROOT / 'output/affinity-auto-evidence_20261024/affinity-auto/live/usb_live_summary.json', 'evidence/summary/affinity_live.json')
    for name in ['analyze_live_usb.py', 'analyze_slam60_cache.py']:
        copy(PLD / '.work' / name, Path('evidence/analysis_tools') / name)
    # Preserve actual historical simulation PASS records, not only prose claims.
    simulations = [PLD / 'zynq_slam/build/video_sim_20261023_174721',
                   PLD / 'zynq_slam/build/video_sim_20261023_174754_600587_tb_video',
                   PLD / '.work/vs18/1023_193605_711430_video_full',
                   PLD / '.work/vs18/1023_183523_936243_serializer']
    for folder in simulations:
        if not folder.is_dir():
            raise ValueError('Historical simulation directory missing: ' + str(folder))
        for path in folder.rglob('*'):
            if path.is_file() and path.name in ['checks.json', 'status.json', 'simulate.log', 'xsim.log', 'simulate.tcl']:
                copy(path, Path('evidence/rtl_simulation') / folder.name / path.relative_to(folder))

    print('DEPENDENCIES: copying fixed offline packages and exact factory source', flush=True)
    for path in (ROOT / 'build/downloads').iterdir():
        if path.is_file() and path.name in ['cmake-3.31.10-windows-x86_64.zip', 'cmake-3.31.10-windows-x86_64.zip.json',
                                            'ninja-win.zip', 'ninja-win.zip.json',
                                            'libjpeg-turbo-3.2.0.tar.gz', 'libjpeg-turbo-3.2.0.tar.gz.json',
                                            'opencv_python_headless-4.13.0.92-cp37-abi3-win_amd64.whl']:
            copy(path, Path('dependencies/offline_packages') / path.name)
    copy(FACTORY, 'dependencies/factory_source/' + FACTORY.name)
    bind(FACTORY, '41e9c2edcf4844f625129437306dcda6f4f1abf279cb8a63d83234a3aee266b5',
         'dependencies/factory_source/' + FACTORY.name, 'factory_source')
    for name in ['fpga-python.cmd', 'zynq-arm-linux-2018.3.cmd', 'xilinx-2018.3.cmd']:
        copy(Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin') / name, Path('dependencies/toolchain_profiles') / name)
    if (ROOT / 'build/calibration_python/provenance.json').exists():
        copy(ROOT / 'build/calibration_python/provenance.json', 'dependencies/opencv_pc_provenance.json')

    # Recheck frozen originals without invoking build, network or board tools.
    frozen = read(BASELINE / 'manifest.json')
    for name, expected in frozen['source_sha256'].items():
        for directory in [BASELINE / 'source', PLD / 'zynq_slam']:
            if sha(directory / name) != expected:
                raise ValueError('Frozen/original source changed: ' + str(directory / name))
    count = 0
    for line in (BASELINE / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        expected, name = line.split('  ', 1)
        if sha(BASELINE / name) != expected:
            raise ValueError('Frozen artifact changed: ' + name)
        count += 1
    write(out / 'evidence/frozen_baseline_audit.json', dict(status='PASS',
          original_and_frozen_source_files=len(frozen['source_sha256']), frozen_artifacts=count,
          scope='Read-only during handoff export; no source, archive or SD changes'))

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    manifest = dict(format_version=1, created_local=now, status='SOURCE_HANDOFF_NOT_ACCEPTED_LIVE_SLAM30',
        original_source_root=str(ROOT), main_build=ARM.name, helper_build=S1.name, uvc_build=UVC.name,
        fpga_export=FINAL.name, target=dict(board='ACZ7015', part='xc7z015clg485-2', top='s_wrapper'),
        current_board_status='UNVERIFIED; 22:25 physical Ethernet disconnected; user last reported replay/startup image',
        board_actions_this_export=False, compilation_this_export=False, synthesis_this_export=False,
        live_camera_30fps_accepted=False, tracking_quality_accepted=False,
        camera_autostart_installed=False,
        verified_bindings=bindings,
        external_datasets=[dict(name='2273-frame original gray input + golden records', bundled=False,
            original_host_archive=str(PLD / '.work/video_inputs_20261023.tar.gz'),
            archive_bytes=854953114, archive_sha256_reference='8dcaeec0a513b6938027b300c93b97e0c941474d40f40cdb0f5b057fb4d13f31',
            raw_bytes=1571097600, board_directory='/opt/zynq-slam/data/video_inputs_20261023',
            golden_reference='arm_replay_20261023_195434',
            verification_scope='Historical archive hash reference only; external large data not rehashed by this export')],
        excluded=['Other historical builds/caches and temporary experiments',
                  'Full old gray recording/golden dataset', 'SDK/Vivado/MinGW/Python installers',
                  'Passwords, SSH private keys and user-global configuration',
                  'Original full RK3588 ORB-SLAM3/UI source (not supplied in original handoff)'],
        history_notice='source/ is authoritative current code; camera_runtime/source.tar.gz and old READMEs/manifests are retained historical release records')
    files = sorted(p for p in out.rglob('*') if p.is_file())
    manifest['file_sha256'] = {p.relative_to(out).as_posix(): sha(p) for p in files}
    write(out / 'manifest.json', manifest)
    sums = dict(manifest['file_sha256'], **{'manifest.json': sha(out / 'manifest.json')})
    (out / 'SHA256SUMS').write_text(''.join(expected + '  ' + name + '\n' for name, expected in sorted(sums.items())), encoding='ascii', newline='\n')
    print('VERIFY: all package files, original manifests and source/artifact bindings', flush=True)
    report = verify(out)
    report['created_local'] = now
    archive = out.with_suffix('.zip')
    if archive.exists():
        raise ValueError('Archive already exists')
    print('ZIP: producing single transferable package', flush=True)
    compressed = {'.zip', '.gz', '.whl', '.dcp', '.hdf', '.png', '.jpg', '.jpeg'}
    with zipfile.ZipFile(archive, 'w', allowZip64=True) as z:
        for path in sorted(out.rglob('*')):
            if path.is_file():
                z.write(path, arcname=out.name + '/' + path.relative_to(out).as_posix(),
                        compress_type=zipfile.ZIP_STORED if path.suffix.lower() in compressed else zipfile.ZIP_DEFLATED,
                        compresslevel=6)
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad:
            raise ValueError('Archive CRC error: ' + bad)
        expected_names = {out.name + '/' + p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
        if len(z.namelist()) != len(expected_names) or set(z.namelist()) != expected_names:
            raise ValueError('Archive membership differs from verified directory')
    report.update(package=str(out), archive=str(archive), archive_bytes=archive.stat().st_size,
                  archive_sha256=sha(archive), zip_crc='PASS', zip_membership='PASS')
    write(archive.with_suffix('.verification.json'), report)
    archive.with_suffix('.zip.sha256').write_text(report['archive_sha256'] + '  ' + archive.name + '\n', encoding='ascii', newline='\n')
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)


if __name__ == '__main__':
    main()
