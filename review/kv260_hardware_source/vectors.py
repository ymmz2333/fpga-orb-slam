"""Synthetic independent acceptance; never presented as board/video throughput."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from .reference import configuration,golden,samples

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    rng=np.random.default_rng(12892);k=np.array([[685.,2.,479.5],[0,681,359.5],[0,0,1]])
    angle=.41;pose=np.eye(4);pose[:3,:3]=[[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]];pose[:3,3]=[-2,1.2,.4]
    cfg=configuration(k,pose);cases=[]
    for i,n in enumerate([0,1,17,256,513,71,64,37,43]):
        x=np.zeros((n,4),'<u4');x[:,0]=rng.uniform(.1,10,n).astype('<f4').view('<u4');x[:,1]=rng.integers(0,1<<32,n,dtype=np.uint32)
        x[:,2]=rng.integers(0,960,n,dtype=np.uint32)|(rng.integers(0,720,n,dtype=np.uint32)<<16);x[:,3]=1
        c=cfg.copy();count=n;capacity=n
        if i==3:
            x[::5,3]=0;x[1::17,0]=np.float32(np.nan).view('u4');x[2::19,0]=np.float32(-1).view('u4');x[3::23,2]=0xffffffff
            x[4::29,0]=np.float32(np.inf).view('u4');x[5::31,0]=0
        if i==4:capacity=23
        if i==5:capacity=0
        if i==6:c[4]=np.nan
        if i==7:count=172801
        if i==8:x[:,3]=0
        cases.append((f'case{i}',x,c,count,capacity))
    yy,xx=np.mgrid[:720,:960];depth=1+xx*.002+yy*.001;rgb=rng.integers(0,256,(720,960,3),dtype=np.uint8)
    full=samples(depth,rgb,((xx+yy)%7)!=0);cases.append(('full_frame',full,cfg,len(full),len(full)))
    items=[]
    for name,x,c,count,cap in cases:
        expected,stats=golden(x,c,count,cap)
        for suffix,value in [('samples',x),('config',c),('points',expected),('stats',stats)]:value.tofile(a.output/f'{name}_{suffix}.bin')
        items.append(dict(name=name,count=count,capacity=cap,stored=len(x),written=len(expected)))
    for mode in ['all','small']:
        chosen=items if mode=='all' else items[:-1]
        (a.output/f'{mode}.txt').write_text('\n'.join(f"{x['name']} {x['count']} {x['capacity']} {x['stored']} {x['written']}" for x in chosen)+'\n')
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.iterdir() if p.is_file()}
    (a.output/'vectors.json').write_text(json.dumps(dict(scope='synthetic geometry and full 960x720 grid, not board measurements',cases=items,sha256=files),indent=2)+'\n')
    print('Independent golden vectors:',len(items))

if __name__=='__main__':main()
