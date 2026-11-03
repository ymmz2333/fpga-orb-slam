"""Prepare pinned VAI 2.5 source, excluding external sample-model symlinks."""
from __future__ import annotations
import hashlib,json,posixpath,tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'orb60/build/kv260_system/vendor_sources/vai25_runtime'
EXPECTED='b8d7928627f02d5b803f34618df6fe1c400123da45cea5b3ca32fc1ac23543b8'


def main():
    source=BASE/'vai25_runtime_source.tar.gz'
    if hashlib.file_digest(source.open('rb'),'sha256').hexdigest()!=EXPECTED:
        raise ValueError('Pinned source archive changed')
    output=BASE/'vai25_runtime_source_safe_v2.tar.gz';omitted=[];count=0
    with tarfile.open(source) as src,tarfile.open(output,'w:gz') as dst:
        for item in src:
            if item.issym() and item.linkname.startswith('/'):
                if '/xmodel_image/models/' not in item.name or not item.name.endswith('.xmodel'):
                    raise ValueError('Unexpected external symlink: '+item.name)
                omitted.append({'name':item.name,'target':item.linkname,'reason':'unrelated sample model reference; no project weight is replaced'})
                continue
            if item.issym():
                target=posixpath.normpath(posixpath.join(posixpath.dirname(item.name),item.linkname))
                if not target.startswith('src/'):
                    raise ValueError('Relative link leaves source root: '+item.name)
            dst.addfile(item,src.extractfile(item) if item.isfile() else None);count+=1
    record={'upstream_commit':'c26eae36f034d5a2f9b2a7bfe816b8c43311a4f8','original_archive_sha256':EXPECTED,
            'archive':output.name,'archive_sha256':hashlib.file_digest(output.open('rb'),'sha256').hexdigest(),
            'members':count,'omitted_external_sample_links':omitted,'runtime_source_changes':[]}
    (BASE/'SAFE_SOURCE_V2_PROVENANCE.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='omitted_external_sample_links'}))


if __name__=='__main__':main()
