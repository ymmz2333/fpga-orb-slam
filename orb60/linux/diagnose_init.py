"""Compare level0/all-level FPGA descriptor matches; never extracts CPU ORB."""
import argparse
import json
from pathlib import Path
import struct
import cv2
import numpy as np
from client import Client,b1_packet


def match(packet0,packet1,all_levels):
    n0=(len(packet0)-64)//64;n1=(len(packet1)-64)//64
    def unpack(packet,n):
        fields=[struct.unpack_from('<ffi3fii',packet,64+64*i) for i in range(n)]
        desc=np.array([list(packet[96+64*i:128+64*i]) for i in range(n)],dtype=np.uint8)
        xy=np.array([[p[0],p[1]] for p in fields],dtype=np.float32).reshape(-1,1,2)
        intrinsic=np.array([[910.072,0,485.523],[0,914.094,336.718],[0,0,1]],dtype=np.float64)
        distortion=np.array([-.005941,.055161,-.006094,.003192],dtype=np.float64)
        xy=cv2.undistortPoints(xy,intrinsic,distortion,P=intrinsic).reshape(-1,2)
        return fields,desc,xy
    f0,d0,xy0=unpack(packet0,n0);f1,d1,xy1=unpack(packet1,n1)
    table=np.array([bin(i).count('1') for i in range(256)],dtype=np.uint8)
    distances=table[np.bitwise_xor(d0[:,None,:],d1[None,:,:])].sum(axis=2)
    matches={};owners={};best_seen={};hist=[[] for _ in range(30)]
    for i,k in enumerate(f0):
        level=k[2]
        if level and not all_levels:continue
        candidates=[j for j,v in enumerate(f1) if v[2]==level and np.all(np.abs(xy1[j]-xy0[i])<100)
                    and best_seen.get(j,2**30)>int(distances[i,j])]
        candidates.sort(key=lambda j:int(distances[i,j]))
        if not candidates:continue
        best=candidates[0];score=int(distances[i,best]);second=int(distances[i,candidates[1]]) if len(candidates)>1 else 2**30
        if score<=50 and score<.9*second:
            if best in owners:matches.pop(owners[best],None)
            matches[i]=best;owners[best]=i;best_seen[best]=score
            angle=(k[3]-f1[best][3])%360
            # Match the original ORBmatcher histogram factor1/30.
            hist[int(np.floor(angle/30+.5))%30].append(i)
    biggest=sorted(range(30),key=lambda i:len(hist[i]),reverse=True)[:3]
    keep={i for b in biggest if len(hist[b])>=.1*len(hist[biggest[0]]) for i in hist[b]}
    matches={i:j for i,j in matches.items() if i in keep}
    return dict(matches=len(matches),initial_level0=sum(p[2]==0 for p in f0),
                current_level0=sum(p[2]==0 for p in f1),all_levels=all_levels)


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    stamps=(a.dataset/'timestamps.txt').read_text().splitlines();client=Client(a.host);packets={};results=[]
    try:
        for index in (0,1,150,151,240,241):
            image=cv2.imread(str(a.dataset/'mav0/cam0/data'/f'{stamps[index]}.png'),cv2.IMREAD_GRAYSCALE)
            assert image is not None and image.shape==(720,960)
            result,payload=client.extract(image.tobytes(),10000+index,int(stamps[index]),1)
            packet=b1_packet(result);packets[index]=packet
            (a.output/f'{index}.orb').write_bytes(packet)
        for first in (0,150,240):
            for all_levels in (False,True):
                item=match(packets[first],packets[first+1],all_levels);item.update(first=first,second=first+1)
                results.append(item);print(json.dumps(item),flush=True)
    finally:client.close()
    (a.output/'matches.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
