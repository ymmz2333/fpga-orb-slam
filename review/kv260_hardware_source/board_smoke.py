"""Explicit post-deployment point-core check. Never loads FPGA or edits system."""
import argparse,hashlib,json,struct,time
from pathlib import Path
import numpy as np
from .reference import configuration,golden,compare
from .runtime import SAMPLE_OFFSET,CONFIG_OFFSET,OUTPUT_OFFSET,STATS_OFFSET
from orb60.kv260.runtime import XrtWorkspace,UioCore

def main():
    p=argparse.ArgumentParser()
    for key in ['uio','abi','release','deployment-receipt','output']:p.add_argument('--'+key,required=True)
    p.add_argument('--uio-name',default='kv260_point_project');a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise ValueError('Fresh board preflight output required')
    release=json.loads(Path(a.release).read_text());receipt=json.loads(Path(a.deployment_receipt).read_text())
    if release.get('platform_kind')!='dpu_points' or not release.get('export_verified'):raise ValueError('Complete matched export required')
    if receipt.get('status')!='DPU_POINTS_LOADED' or receipt.get('bitstream_sha256')!=release['sha256']['kv260_dpu_points.bit']:
        raise ValueError('Explicit successful deployment receipt must name this exact bitstream')
    if receipt.get('dpu_fingerprint')!=release['dpu_fingerprint']:raise ValueError('Loaded DPU fingerprint mismatch')
    if hashlib.sha256(Path(a.abi).read_bytes()).hexdigest()!=release['sha256']['point_abi.json']:raise ValueError('ABI changed')
    abi=json.loads(Path(a.abi).read_text());memory=XrtWorkspace();core=None;results=[]
    try:
        core=UioCore(a.uio,a.uio_name,0xA2000000,abi)
        conf=configuration(np.array([[600.,0,480],[0,600,360],[0,0,1]]),np.eye(4))
        data=np.zeros((6,4),'<u4');data[:,0]=np.array([1,2,0,np.nan,-1,np.inf],'<f4').view('<u4')
        data[:,1]=[0x030201,0x405060,1,2,3,4];data[:,2]=[20|30<<16,959|719<<16,0,0,0,0];data[:,3]=1
        for count,capacity in [(6,6),(0,0),(6,1),(6,0)]:
            expected,stats=golden(data,conf,count,capacity)
            for off,payload in [(SAMPLE_OFFSET,data.tobytes()),(CONFIG_OFFSET,conf.tobytes()),(STATS_OFFSET,b'\xa5'*32)]:
                memory.buffer[off:off+len(payload)]=payload;memory.sync(off,len(payload),True)
            if not core.read('AP_CTRL')&4:raise RuntimeError('Kernel is not idle')
            for name,off in [('SAMPLES',SAMPLE_OFFSET),('CONFIG_R',CONFIG_OFFSET),('POINTS',OUTPUT_OFFSET),('STATS',STATS_OFFSET)]:core.write(name+'_DATA',memory.address+off)
            core.write('COUNT_DATA',count);core.write('CAPACITY_DATA',capacity);began=time.monotonic();core.write('AP_CTRL',1)
            while not core.read('AP_CTRL')&2:
                if time.monotonic()-began>3:raise TimeoutError('Point hardware timed out')
                time.sleep(.0001)
            memory.sync(STATS_OFFSET,32,False)
            actual=bytes(memory.buffer[STATS_OFFSET:STATS_OFFSET+32])
            if actual!=stats.tobytes() or core.read('AP_RETURN')!=int(stats[3]):raise ValueError('Point hardware status mismatch')
            n=int(stats[2]);memory.sync(OUTPUT_OFFSET,max(32,n*32),False)
            points=np.frombuffer(bytes(memory.buffer[OUTPUT_OFFSET:OUTPUT_OFFSET+n*32]),'<u4').reshape(-1,8);compare(points,expected)
            results.append(dict(count=count,capacity=capacity,written=n))
        proof=dict(status='DPU_POINTS_BOARD_PREFLIGHT_PASS',platform_kind='dpu_points',point_control_address=0xA2000000,
            point_uio_name=a.uio_name,abi_sha256=hashlib.sha256(Path(a.abi).read_bytes()).hexdigest(),
            bitstream_sha256=receipt['bitstream_sha256'],tests=results,scope='Actual small-point vectors, not video FPS or complete dense fusion acceptance')
        out.write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
    finally:
        if core:core.close()
        memory.close()
if __name__=='__main__':main()
