#!/usr/bin/env python3
"""Independent little-endian packet reader and direct in-memory snapshot comparison."""
import argparse
import csv
import hashlib
import json
import math
import pathlib
import struct

HEADER=struct.Struct('<8sHHHBBQIIII f IIIiI')
RECORD=struct.Struct('<ffi fff iI32s')
assert HEADER.size==RECORD.size==64

def verify(path,memory,ns,role,nfeatures=1000):
    data=path.read_bytes()
    if len(data)<64:
        raise ValueError('truncated header: '+str(path))
    h=HEADER.unpack_from(data)
    magic,version,header,record,r,flags,t,width,height,count,levels,scale,features,desc,coords,mono,reserved=h
    if (magic,version,header,record,r,flags,t,width,height,levels,features,desc,coords,reserved)!=(
            b'ORBFEAT\0',1,64,64,role,0,ns,752,480,8,nfeatures*(5 if role else 1),32,0,0):
        raise ValueError('header mismatch: '+str(path))
    if struct.pack('<f',scale)!=struct.pack('<f',1.2) or not 0<=mono<=count or len(data)!=64+64*count:
        raise ValueError('scale/count/length mismatch: '+str(path))
    snapshot=memory.read_bytes()
    # Full comparison, not merely a digest; snapshot was independently copied from cv::KeyPoint/cv::Mat.
    if data[64:]!=snapshot:
        raise ValueError('memory byte mismatch: '+str(path))
    for values in RECORD.iter_unpack(data[64:]):
        x,y,octave,angle,size,response,class_id,reserved,descriptor=values
        if not all(math.isfinite(v) for v in (x,y,angle,size,response)) or not (
                0<=x<width and 0<=y<height and 0<=octave<levels and 0<=angle<360 and size>0 and reserved==0):
            raise ValueError('invalid point: '+str(path))
    return dict(timestamp_ns=ns,role=role,point_count=count,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                memory_bytes=len(snapshot),byte_equal=True)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--corpus',required=True); p.add_argument('--timestamps')
    p.add_argument('--output',required=True); p.add_argument('--fixture',action='store_true')
    p.add_argument('--synthetic',action='store_true',help='Only for the deterministic 24-frame A1 startup input')
    a=p.parse_args()
    root=pathlib.Path(a.corpus); output=pathlib.Path(a.output); output.mkdir(parents=True,exist_ok=True)
    if a.fixture:
        rows=[verify(root/'fixture.orb',root/'fixture.bin',1403636579763555584,0),
              verify(root/'empty.orb',root/'empty.bin',1403636579763555584,0)]
    else:
        timestamps=[int(line) for line in pathlib.Path(a.timestamps).read_text().splitlines() if line.strip()]
        if len(timestamps)!=(24 if a.synthetic else 3682) or len(set(timestamps))!=len(timestamps):
            raise ValueError('MH01 timestamp count/uniqueness mismatch')
        rows=[]
        for role,name in enumerate(('normal','initialization')):
            expected={str(ns)+'.orb' for ns in timestamps}
            if {path.name for path in (root/name).glob('*.orb')}!=expected:
                raise ValueError('incomplete or extra corpus role: '+name)
            for ns in timestamps:
                rows.append(verify(root/name/(str(ns)+'.orb'),root/'memory'/name/(str(ns)+'.bin'),ns,role))
    with (output/'feature_verification.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    result=dict(status='PASS',files=len(rows),points=sum(r['point_count'] for r in rows),
                byte_mismatches=0,bytes_compared=sum(r['memory_bytes'] for r in rows),fixture=a.fixture,synthetic_only=a.synthetic)
    (output/'feature_verification.json').write_text(json.dumps(result,indent=2))
    print('FEATURE_VERIFICATION '+json.dumps(result))

if __name__=='__main__': main()
