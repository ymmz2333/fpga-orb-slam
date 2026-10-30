"""Portable readers for the frozen ORB60 localization handoff (no hardware dependency)."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

RECORD=np.dtype([('x','<u4'),('y','<u4'),('score','<u4'),('level','<u4'),('bin','<u4'),
                 ('m10','<i4'),('m01','<i4'),('angle','<u4'),('descriptor','u1',(32,))])

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.part');tmp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8');tmp.replace(path)
def rows(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:return list(csv.DictReader(stream))
def write_rows(path,data,fields=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(data[0]));writer.writeheader();writer.writerows(data)

def feature_points(records):
    scales=np.empty(8,np.float32);scales[0]=1
    for i in range(1,8):scales[i]=scales[i-1]*np.float32(1.2)
    return np.column_stack((records['x'].astype(np.float32)*scales[records['level']],
                            records['y'].astype(np.float32)*scales[records['level']]))

class Features:
    def __init__(self,root):
        self.root=Path(root);self.index=rows(self.root/'frames.csv')
        offset=0
        for i,row in enumerate(self.index):
            count=int(row['count'])
            if int(row['frame_index'])!=i or int(row['record_offset'])!=offset or not 0<=count<=1000:
                raise ValueError('Invalid feature frame order/count/offset')
            offset+=count
        if (self.root/'features.bin').stat().st_size!=offset*RECORD.itemsize:
            raise ValueError('Truncated or extra feature bytes')
        self.data=np.memmap(self.root/'features.bin',dtype=RECORD,mode='r')
    def frame(self,index):
        row=self.index[index];first=int(row['record_offset']);count=int(row['count'])
        return self.data[first:first+count]
    def close(self):
        """Release Windows file mapping after all borrowed frame views are discarded."""
        self.data._mmap.close()
    def __enter__(self):return self
    def __exit__(self,*unused):self.close()

def pose_from_row(row,prefix='twc_'):
    return np.array([[float(row[prefix+str(r)+str(c)]) for c in range(4)] for r in range(4)])
def pose_fields(pose):return {'twc_%d%d'%(r,c):float(pose[r,c]) for r in range(4) for c in range(4)}
def pose_error(reference,candidate,depth):
    relative=reference[:3,:3].T@candidate[:3,:3]
    angle=np.degrees(np.arccos(np.clip((np.trace(relative)-1)*.5,-1,1)))
    return float(np.linalg.norm(candidate[:3,3]-reference[:3,3])/depth),float(angle)
