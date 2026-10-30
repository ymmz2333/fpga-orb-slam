"""Freeze compact B2 evidence; publish FINISHED only after the archive is complete."""
import csv,hashlib,pathlib,tarfile

def package(root):
    root=pathlib.Path(root)
    excluded={'batch_state.json','raw_manifest.csv','results.tar.gz'}
    paths=[p for p in root.rglob('*') if p.is_file() and 'corpus' not in p.relative_to(root).parts and p.name not in excluded]
    with (root/'raw_manifest.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);w.writeheader()
        for path in sorted(paths):w.writerow(dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    with tarfile.open(root/'results.tar.gz','w:gz') as archive:
        for path in paths+[root/'raw_manifest.csv']:archive.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
    return hashlib.sha256((root/'results.tar.gz').read_bytes()).hexdigest()
