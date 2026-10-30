from pathlib import Path
import json, hashlib, urllib.request, tarfile, zipfile, importlib.util
root=Path(__file__).resolve().parents[1];cache=root/'build/downloads';cache.mkdir(parents=True,exist_ok=True)
pins={'libjpeg-turbo-3.2.0.tar.gz':'6f30092cef9fb839779646608f4ee14ae3cbac989c47fa05e841b0841f09878e','cmake-3.31.10-windows-x86_64.zip':'13d1a463d7130df5339baedd63d8ae990aaf385062b2f42f372796143ae94086','ninja-win.zip':'07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65'}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'zynq-usb-camera-source-setup'}),timeout=40)
def asset(repo,tag,name):
    with get('https://api.github.com/repos/'+repo+'/releases/tags/'+tag) as r:release=json.load(r)
    meta=next(a for a in release['assets'] if a['name']==name);dst=cache/name
    if not dst.exists():
        part=dst.with_name(dst.name+'.part')
        with get(meta['browser_download_url']) as r,part.open('wb') as f:
            for block in iter(lambda:r.read(1024*1024),b''):f.write(block)
        part.rename(dst)
    h=hashlib.sha256(dst.read_bytes()).hexdigest();expected=meta.get('digest')
    if h!=pins[name]:raise RuntimeError('Pinned release SHA mismatch: '+name)
    if expected and expected!='sha256:'+h:raise RuntimeError('Official asset SHA mismatch: '+name)
    provenance=dict(repository=repo,tag=tag,url=meta['browser_download_url'],sha256=h,official_api_digest=expected,bytes=dst.stat().st_size)
    (dst.with_name(dst.name+'.json')).write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance),flush=True);return dst,provenance
src,meta=asset('libjpeg-turbo/libjpeg-turbo','3.2.0','libjpeg-turbo-3.2.0.tar.gz')
out=root/'vendor/jpeg_turbo';out.mkdir(exist_ok=True)
upstream=out/'upstream';upstream.mkdir(exist_ok=True);manifest={}
with tarfile.open(src,'r:gz') as tar:
    for m in tar:
        parts=Path(m.name).parts
        if parts[0]!='libjpeg-turbo-3.2.0' or '..' in parts or m.issym() or m.islnk():raise RuntimeError('Unexpected source archive member')
        if not m.isfile():continue
        rel=Path(*parts[1:]);data=tar.extractfile(m).read();manifest[rel.as_posix()]=hashlib.sha256(data).hexdigest()
        dst=upstream/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and dst.read_bytes()!=data:raise RuntimeError('Frozen upstream source modified: '+str(rel))
        if not dst.exists():dst.write_bytes(data)
if {p.relative_to(upstream).as_posix() for p in upstream.rglob('*') if p.is_file()}!=set(manifest):raise RuntimeError('Unexpected extra frozen JPEG source')
(out/'provenance.json').write_text(json.dumps(dict(meta,source_sha256=manifest),indent=2)+'\n')
for repo,tag,name,folder in [('Kitware/CMake','v3.31.10','cmake-3.31.10-windows-x86_64.zip','cmake'),('ninja-build/ninja','v1.13.2','ninja-win.zip','ninja')]:
    src,_=asset(repo,tag,name);dst=root/'build/tools'/folder
    dst.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(src) as z:
        for member in z.infolist():
            if Path(member.filename).is_absolute() or '..' in Path(member.filename).parts:raise RuntimeError('Unsafe zip member')
            if member.is_dir():continue
            path=dst/member.filename;data=z.read(member);path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.read_bytes()!=data:raise RuntimeError('Portable tool differs from pinned archive: '+member.filename)
            if not path.exists():path.write_bytes(data)
print('PINNED_CAMERA_DEPENDENCIES_READY; no compiler started',flush=True)
