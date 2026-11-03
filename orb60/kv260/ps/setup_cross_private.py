"""Unpack authenticated compiler and board headers into one fresh private folder."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import posixpath
import tarfile


def unpack(archive,output):
    output.mkdir(parents=True,exist_ok=False)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or member.isdev() or member.isfifo():raise ValueError('Unsafe archive member')
            if member.issym() or member.islnk():
                target=posixpath.normpath(posixpath.join(str(name.parent) if member.issym() else '',member.linkname))
                if target.startswith('/') or target=='..' or target.startswith('../'):raise ValueError('Archive link escapes private folder')
        tar.extractall(output)


def run(package,output):
    package,output=Path(package),Path(output)
    binary=package/'toolchain.tar.xz';headers=package/'board_sysroot.tar.gz'
    expected=(package/'toolchain.asc').read_text().split()[0]
    def hash_file(path,name):
        value=hashlib.new(name)
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):value.update(block)
        return value.hexdigest()
    if hash_file(binary,'md5')!=expected:raise ValueError('Official toolchain checksum mismatch')
    if hash_file(headers,'sha256')!='ded2341db160ee076f35aa2af45867f21cb8fcf812e03d7aff9c4fd414b2d615':
        raise ValueError('Actual board header archive mismatch')
    output.mkdir(parents=True,exist_ok=False)
    unpack(binary,output/'toolchain');unpack(headers,output/'sysroot')
    record={'status':'PRIVATE_CROSS_INPUTS_UNPACKED','toolchain_md5':expected,'toolchain_sha256':hash_file(binary,'sha256'),
            'sysroot_sha256':hash_file(headers,'sha256'),'source':'Official Arm HTTPS download and current KV260 headers',
            'system_packages_modified':False,'RK_environment_modified':False}
    (output/'INPUTS.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
