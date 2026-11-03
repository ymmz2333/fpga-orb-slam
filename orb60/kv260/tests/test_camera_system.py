import json
from pathlib import Path
import pytest
from orb60.kv260.run_camera_mapping import verify_build
from orb60.kv260.run_network_system import digest
from orb60.kv260.camera_status import label
from orb60.kv260.run_camera_system import record_startup_failure


def fixture(root):
    (root/'source').mkdir();(root/'bin').mkdir()
    source=root/'source/camera.cc';source.write_bytes(b'retained camera source')
    exe=root/'bin/mono_kv260_camera';exe.write_bytes(b'component-test executable')
    lib=root/'libORB_SLAM3.so';lib.write_bytes(b'retained mapping DSO')
    data=dict(status='NATIVE_CAMERA_ENTRY_BUILD_PASS',protected_sha256={str(lib):digest(lib)},
              products_sha256={str(exe):digest(exe)},source_sha256={'camera.cc':digest(source)},
              retained_mapping_dso={str(lib):digest(lib)})
    (root/'BUILD.json').write_text(json.dumps(data))
    return lib,source


def test_camera_runtime_checks_exact_retained_dso_and_source(tmp_path):
    lib,source=fixture(tmp_path)
    proof=verify_build(tmp_path,{},lambda command,env:f'libORB_SLAM3.so => {lib} (0x1234)\n')
    assert str(source) in proof and str(lib) in proof and str(tmp_path/'BUILD.json') in proof


@pytest.mark.parametrize('case',('preload','changed_source','wrong_library','unresolved'))
def test_native_runtime_binding_cannot_silently_change(tmp_path,case):
    lib,source=fixture(tmp_path);env={};text=f'libORB_SLAM3.so => {lib} (0x1234)\n'
    if case=='preload':env['LD_PRELOAD']='substitute.so'
    if case=='changed_source':source.write_bytes(b'changed')
    if case=='wrong_library':text=f'libORB_SLAM3.so => {tmp_path}/other.so (0x1234)\n'
    if case=='unresolved':text+='libfoo => not found\n'
    with pytest.raises(ValueError):verify_build(tmp_path,env,lambda command,env:text)


def test_window_never_labels_empty_or_lost_camera_as_dense_map():
    assert label({'pose_valid':False},0,0)=='等待初始化，请缓慢平移相机'
    assert label({'pose_valid':False},100,200)=='跟踪中断'
    assert label({'pose_valid':True},100,0)=='建图中，等待彩色点云'
    assert label({'pose_valid':True},100,200)=='彩色稠密点云'


def test_failed_readonly_startup_is_recorded_without_clobbering_runs(tmp_path):
    out=tmp_path/'run';control=tmp_path/'run_control'
    record_startup_failure(out,ValueError('stale boot proof'))
    r=json.loads((control/'RESULT.json').read_text());assert r['status']=='FAILED_STARTUP' and not r['mapping_verified']
    original=(control/'RESULT.json').read_bytes();record_startup_failure(out,ValueError('second attempt'))
    assert (control/'RESULT.json').read_bytes()==original
    other=tmp_path/'other';other.mkdir();record_startup_failure(other,ValueError('existing run'))
    assert not (tmp_path/'other_control').exists()
