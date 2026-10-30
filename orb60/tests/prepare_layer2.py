"""Independent Python full-image oracle for the shared-reader 2PPC layer.

Reference math imports no DUT tables. Frozen C++ FAST vectors must independently
agree before vendor C simulation starts. Binary images also serve later AXI tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from oracle import LAYER2_CASES, WIDTHS, HEIGHTS, BUDGETS, pixels, packed_image, front, gaussian, resize


def prepare(job, output):
    output.mkdir(parents=True,exist_ok=False)
    summary_text,points_text=(job/'inputs/layer2_vectors.inc').read_text().split('static const fastv2::Point')
    cpp_summaries=[list(map(int,re.findall(r'-?\d+',row))) for row in re.findall(r'\{([^{}]+)\}',summary_text)]
    cpp_points=[[tuple(map(int,p.split(','))) for p in re.findall(r'\{(-?\d+,-?\d+,-?\d+,-?\d+)\}',row)]
                for row in points_text.splitlines()[1:-1]]
    assert len(cpp_summaries)==len(cpp_points)==len(LAYER2_CASES)
    cases=[]
    cache={}
    for i,test in enumerate(LAYER2_CASES):
        level,pattern,high,low,dual,capacity,delta=test
        key=(level,pattern)
        if key not in cache:
            raw=pixels(level,pattern,front=True)
            cache[key]=(raw,gaussian(raw),resize(raw,level) if level<7 else None)
        raw,blur,smaller=cache[key]
        summary,points=front(raw,test)
        assert summary==cpp_summaries[i], f'Layer2 Python/C++ summary mismatch case={i}'
        assert points==(cpp_points[i] if points else []), f'Layer2 Python/C++ points mismatch case={i}'
        name=f'layer2_{i:02}'
        record=bytearray(b'\xa5'*16000)
        for j,point in enumerate(points): record[16*j:16*(j+1)]=struct.pack('<4i',*point)
        files={'input':packed_image(raw), 'points':bytes(record),
               'summary':struct.pack('<I12i3I',*summary),
               'blur':packed_image(blur if not delta else None,output=True),
               'resize':packed_image(smaller if not delta else None,output=True)}
        for suffix,data in files.items(): (output/f'{name}_{suffix}.bin').write_bytes(data)
        cases.append(dict(kernel='layer2',index=i,name=name,level=level,pattern=pattern,status=summary[1],
                          selected=summary[3],candidates=summary[2],
                          args=[level,BUDGETS[level]+delta,high,low,dual,capacity]))
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.bin')}
    (output/'vectors.json').write_text(json.dumps(dict(cases=cases,sha256=hashes,
        fast_python_cpp_exact=len(cases),scope='Independent full-image Gaussian/Resize and frozen FAST references'),indent=2)+'\n')
    print(f'ORB60_LAYER2_PYTHON_ORACLE_PASS cpp_crosscheck={len(cases)}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();prepare(a.job,a.output)
