"""Verify the selected private PS library under the actual runtime environment."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ALLOWED = {
    'NATIVE_NETWORK_ADAPTER_BUILD_PASS', 'NATIVE_CROSS_POSE_LINK_PASS',
    'NATIVE_NEON_DISTANCE_CANDIDATE_PASS', 'NATIVE_MAPPER_SCHEDULING_CANDIDATE_PASS',
    'NATIVE_MAPPER_PUBLICATION_CANDIDATE_PASS', 'NATIVE_NEON_POSE_COMPOSITION_PASS',
    'NATIVE_LOCAL_BA_COMPOSITION_PASS',
    'NATIVE_KEYFRAME_CADENCE_COMPOSITION_PASS',
    'NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS',
    'NATIVE_RAM_BMP_PREVIEW_COMPONENT_PASS',
    'NATIVE_MONO_QUEUE_CANDIDATE_PASS',
    'NATIVE_DIRECT_GRAY_COMPONENT_PASS',
    'NATIVE_REFERENCE_SEED_COMPONENT_PASS',
    'NATIVE_PACKED_YUV_COMPONENT_PASS',
    'NATIVE_PACKED_STREAM_COMPONENT_PASS',
    'NATIVE_PACKED_ARM_CRC_COMPONENT_PASS',
    'NATIVE_PACKED_BMP_COMPONENT_PASS',
    'NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS',
    'NATIVE_TRACKING_TRACE_BUILD_PASS',
    'NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS',
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check_unchanged(proof):
    for path, expected in proof['file_sha256'].items():
        if digest(path) != expected:
            raise ValueError('Selected native build product changed: ' + path)


def verify(manifest, executable, env, linker=None):
    manifest, executable = Path(manifest).resolve(), Path(executable).resolve()
    build = json.loads(manifest.read_text())
    if build.get('status') not in ALLOWED or env.get('LD_PRELOAD'):
        raise ValueError('Explicit completed native build and no preload required')
    products = build['products_sha256']
    libraries = [Path(k) for k in products if Path(k).name == 'libORB_SLAM3.so']
    if len(libraries) != 1 or str(executable) not in products or executable.name != 'mono_kv260_network':
        raise ValueError('Selected native executable/library not in build manifest')
    library = libraries[0].resolve()
    proof = dict(status='NATIVE_RUNTIME_PRODUCTS_VERIFIED', build_status=build['status'],
                 file_sha256={str(manifest): digest(manifest), str(executable): products[str(executable)],
                              str(library): products[str(libraries[0])]})
    check_unchanged(proof)
    if linker is None:
        def linker(command, env):
            return subprocess.check_output(command, env=env, text=True, stderr=subprocess.STDOUT)
    linked = linker(['ldd', str(executable)], env=env)
    if 'not found' in linked or 'undefined symbol' in linked:
        raise ValueError('Unresolved native runtime dependency')
    matched = re.findall(r'^\s*libORB_SLAM3\.so\s+=>\s+(.+?)\s+\(0x[0-9a-fA-F]+\)\s*$', linked, re.M)
    if len(matched) != 1 or Path(matched[0]).resolve() != library:
        raise ValueError('Runtime resolves a different SLAM library')
    proof['resolved_slam_library'] = str(library)
    return proof
