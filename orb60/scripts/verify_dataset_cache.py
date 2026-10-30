"""Verify immutable PNG SHA256, evict only a mismatching clean cached file and re-read."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.dataset.resolve()
    results=[];total=0
    with (root/'frames.csv').open() as f:
        for row in csv.DictReader(f):
            path=(root/row['image']).resolve();assert root in path.parents
            expected=row['sha256'];before=hashlib.sha256(path.read_bytes()).hexdigest();total+=1
            if before!=expected:
                fd=os.open(str(path),os.O_RDONLY)
                try:os.posix_fadvise(fd,0,0,os.POSIX_FADV_DONTNEED)
                finally:os.close(fd)
                after=hashlib.sha256(path.read_bytes()).hexdigest()
                results.append(dict(image=row['image'],expected=expected,cached=before,reread=after))
                if after!=expected:
                    a.output.write_text(json.dumps(dict(status='FAILED',checked=total,mismatches=results),indent=2)+'\n')
                    raise RuntimeError('File still mismatches after clean cache eviction: '+str(path))
    report=dict(status='PASS',checked=total,mismatches=results,original_files_modified=False,
                scope='read-only hashes, not a proof of board memory stability')
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
