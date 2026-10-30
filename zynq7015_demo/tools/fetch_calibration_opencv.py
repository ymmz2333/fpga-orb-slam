"""Optional Windows PC-only calibration dependency; never installed on the Zynq."""
from pathlib import Path
import hashlib,json,urllib.request,zipfile,sys
ROOT=Path(__file__).resolve().parents[1]
VERSION='4.13.0.92'
NAME='opencv_python_headless-4.13.0.92-cp37-abi3-win_amd64.whl'
SHA='77a82fe35ddcec0f62c15f2ba8a12ecc2ed4207c17b0902c7a3151ae29f37fb6'
def main():
    if sys.platform!='win32' or sys.maxsize<2**32:raise RuntimeError('This helper pins the Windows x64 PC wheel')
    folder=ROOT/'build/calibration_python';folder.mkdir(parents=True,exist_ok=True)
    cache=ROOT/'build/downloads';cache.mkdir(exist_ok=True);wheel=cache/NAME
    with urllib.request.urlopen('https://pypi.org/pypi/opencv-python-headless/'+VERSION+'/json',timeout=30) as r:meta=json.load(r)
    asset=next(f for f in meta['urls'] if f['filename']==NAME)
    if asset['digests']['sha256']!=SHA:raise RuntimeError('PyPI wheel digest differs from pinned release')
    if not wheel.exists():
        part=wheel.with_suffix('.part')
        with urllib.request.urlopen(asset['url'],timeout=45) as r,part.open('wb') as f:
            for block in iter(lambda:r.read(1024*1024),b''):f.write(block)
        part.rename(wheel)
    with wheel.open('rb') as f:
        digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=SHA:raise RuntimeError('Downloaded calibration wheel SHA mismatch')
    manifest={}
    with zipfile.ZipFile(wheel) as z:
        for member in z.infolist():
            rel=Path(member.filename)
            if rel.is_absolute() or '..' in rel.parts:raise RuntimeError('Unsafe wheel member')
            if member.is_dir():continue
            path=folder/rel;path.parent.mkdir(parents=True,exist_ok=True);data=z.read(member);h=hashlib.sha256(data).hexdigest();manifest[member.filename]=h
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=h:raise RuntimeError('Existing PC calibration dependency modified: '+str(rel))
            if not path.exists():path.write_bytes(data)
    (folder/'provenance.json').write_text(json.dumps(dict(package='opencv-python-headless',version=VERSION,wheel=NAME,sha256=SHA,url=asset['url'],scope='PC offline calibration only; no global installation, no ARM runtime dependency',file_sha256=manifest),indent=2)+'\n')
    print('PC_CALIBRATION_OPENCV_READY',folder,flush=True)
if __name__=='__main__':main()
