import json
from pathlib import Path
import pytest
from orb60.kv260.native_products import verify, digest, check_unchanged


def setup(tmp_path):
    exe = tmp_path / 'mono_kv260_network';lib = tmp_path / 'libORB_SLAM3.so';manifest = tmp_path / 'BUILD.json'
    exe.write_bytes(b'fixture executable');lib.write_bytes(b'fixture library')
    manifest.write_text(json.dumps(dict(status='NATIVE_LOCAL_BA_COMPOSITION_PASS',
        products_sha256={str(p): digest(p) for p in (exe, lib)})))
    return exe, lib, manifest


def test_actual_runtime_resolution_and_final_product_integrity(tmp_path):
    exe, lib, manifest = setup(tmp_path)
    seen = []
    def linker(command, env):
        seen.append((command, env));return ' libORB_SLAM3.so => %s (0x1234)\n' % lib
    env = {'LD_LIBRARY_PATH': str(tmp_path)}
    proof = verify(manifest, exe, env, linker)
    assert seen == [(['ldd', str(exe)], env)]
    lib.write_bytes(b'modified during run')
    with pytest.raises(ValueError):check_unchanged(proof)


@pytest.mark.parametrize('resolved', ['not found', '/different/libORB_SLAM3.so (0x1234)'])
def test_missing_or_shadowed_library_is_rejected(tmp_path, resolved):
    exe, lib, manifest = setup(tmp_path)
    with pytest.raises(ValueError):
        verify(manifest, exe, {}, lambda command, env: 'libORB_SLAM3.so => ' + resolved)


def test_incomplete_build_or_preload_is_rejected(tmp_path):
    exe, lib, manifest = setup(tmp_path)
    with pytest.raises(ValueError):verify(manifest, exe, {'LD_PRELOAD': 'other.so'})
    d = json.loads(manifest.read_text());d['status'] = 'RUNNING';manifest.write_text(json.dumps(d))
    with pytest.raises(ValueError):verify(manifest, exe, {})
