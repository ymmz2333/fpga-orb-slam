"""Create a checksum-indexed, independent native KV260 build/GUI payload."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[2]


def package(source,output):
    files={}
    def add_tree(tree,prefix,pattern='*'):
        for path in sorted(tree.rglob(pattern)):
            relative=path.relative_to(tree)
            generated=any(part.startswith('build') or part in ('__pycache__','.git') for part in relative.parts[:-1])
            if path.is_file() and not generated and not (prefix=='slam' and relative.as_posix()=='Thirdparty/g2o/config.h'):
                files[prefix+'/'+path.relative_to(tree).as_posix()]=path
    add_tree(source,'slam')
    add_tree(ROOT/'orb60/kv260','sources/orb60/kv260')
    add_tree(ROOT/'orb60/viewer','sources/orb60/viewer','*.py')
    add_tree(ROOT/'orb60/dense','sources/orb60/dense','*.py')
    for name in ('protocol.py','__init__.py','calibration.py','map_bundle.py','export_map.py','dense_environment.py'):
        files['sources/orb60/demo_bridge/'+name]=ROOT/'orb60/demo_bridge'/name
    for name in ('orb60/__init__.py','orb60/viewer/__init__.py'):
        if (ROOT/name).exists():files['sources/'+name]=ROOT/name
    # The physical Ethernet frontend adapter also needs its strict wire codec.
    # No board credentials or generated server binaries are included here.
    files['sources/orb60/linux/client.py']=ROOT/'orb60/linux/client.py'
    files['vocabulary/ORBvoc.txt.tar.gz']=ROOT/'rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3/Vocabulary/ORBvoc.txt.tar.gz'
    # All dependencies are predownloaded for the actual Python 3.10 AArch64 ABI.
    for path in (ROOT/'orb60/build/kv260_system/gui_wheels').glob('*.whl'):
        files['wheels/'+path.name]=path
    manifest={name:None for name in files}
    for required in ('slam/src/System.cc','slam/src/Tracking.cc','slam/include/FpgaORB.h','slam/Examples/Monocular/mono_kv260.cc','sources/orb60/kv260/gui.py'):
        if required not in manifest:raise ValueError('Incomplete source payload: '+required)
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest_path=output.with_suffix('.manifest.json')
    with tarfile.open(output,'w:gz') as archive:
        for name,path in files.items():
            data=path.read_bytes();manifest[name]=hashlib.sha256(data).hexdigest()
            info=archive.gettarinfo(str(path),arcname=name);info.size=len(data)
            archive.addfile(info,io.BytesIO(data))
        data=(json.dumps(manifest,indent=2)+'\n').encode();manifest_path.write_bytes(data)
        info=tarfile.TarInfo('SHA256.json');info.size=len(data);archive.addfile(info,io.BytesIO(data))
    print(json.dumps({'archive':str(output),'files':len(files),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();package(a.source,a.output)
