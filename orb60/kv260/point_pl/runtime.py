"""Explicit new-platform UIO + XRT geometry; never silently falls back to CPU."""
import hashlib,json,struct,time,threading
from pathlib import Path
import numpy as np
from .reference import MAX_SAMPLES,MAGIC,configuration,samples
from orb60.kv260.runtime import XrtWorkspace,UioCore

SAMPLE_OFFSET=0x1000
CONFIG_OFFSET=0x300000
OUTPUT_OFFSET=0x301000
STATS_OFFSET=0x900000

class Projector:
    def __init__(self,uio,abi_file,preflight_file,device_index=0,timeout=3.,memory_backend='xrt'):
        preflight=json.loads(Path(preflight_file).read_text());abi=json.loads(Path(abi_file).read_text())
        if preflight.get('status')!='DPU_POINTS_BOARD_PREFLIGHT_PASS' or preflight.get('point_control_address')!=0xA2000000:
            raise ValueError('Explicit board verification of the DPU+points platform required')
        if preflight.get('abi_sha256')!=hashlib.sha256(Path(abi_file).read_bytes()).hexdigest():raise ValueError('ABI/preflight mismatch')
        if preflight.get('platform_kind')!='dpu_points':raise ValueError('DPU-only or ORB-only platform is incompatible')
        if preflight.get('memory_backend','xrt')!=memory_backend:raise ValueError('Point allocator does not match board verification')
        self.memory=None;self.core=None;self.failed=False;self.timeout=timeout;self.lock=threading.Lock();self.reference_check=None
        try:
            from .native_memory import allocate
            self.memory=allocate(memory_backend,device_index)
            if self.memory.address+len(self.memory.buffer)>0x80000000:raise ValueError('Point BO lies outside verified HP2 low-DDR map')
            self.core=UioCore(uio,preflight['point_uio_name'],0xA2000000,abi)
        except Exception:self.close();raise

    def project(self,depth,rgb,mask,k,twc):
        if not self.lock.acquire(blocking=False):raise RuntimeError('Point projector accepts one outstanding request')
        try:return self._project(depth,rgb,mask,k,twc)
        finally:self.lock.release()

    def _project(self,depth,rgb,mask,k,twc):
        if self.failed:raise RuntimeError('Previous PL failure; platform recovery required')
        began=time.perf_counter_ns();data=samples(depth,rgb,mask);calib=configuration(k,twc)
        n=len(data);self.last_timings={'pack_ns':time.perf_counter_ns()-began}
        if n>MAX_SAMPLES:raise ValueError('Input exceeds fixed hardware capacity')
        try:
            for offset,payload in [(SAMPLE_OFFSET,data.tobytes()),(CONFIG_OFFSET,calib.tobytes()),(STATS_OFFSET,b'\xa5'*32)]:
                self.memory.buffer[offset:offset+len(payload)]=payload;self.memory.sync(offset,len(payload),True)
            if not self.core.read('AP_CTRL')&4:raise RuntimeError('Point core is not idle')
            self.core.write('GIE',0)
            for name,offset in [('SAMPLES',SAMPLE_OFFSET),('CONFIG_R',CONFIG_OFFSET),('POINTS',OUTPUT_OFFSET),('STATS',STATS_OFFSET)]:
                self.core.write(name+'_DATA',self.memory.address+offset)
            self.core.write('COUNT_DATA',n);self.core.write('CAPACITY_DATA',n)
            launch=time.perf_counter_ns();self.core.write('AP_CTRL',1);deadline=time.monotonic()+self.timeout
            while not self.core.read('AP_CTRL')&2:
                if time.monotonic()>deadline:raise TimeoutError('Point projection core timed out')
                time.sleep(.0001)
            self.last_timings['request_ns']=time.perf_counter_ns()-launch
            self.memory.sync(STATS_OFFSET,32,False);s=struct.unpack_from('<8I',self.memory.buffer,STATS_OFFSET)
            if self.core.read('AP_RETURN') or s[3] or s[4:]!=(MAGIC,1,0,0) or s[0]!=n or s[1]!=s[2] or s[2]>n:
                raise RuntimeError('Hardware completion/status mismatch')
            count=s[2];self.memory.sync(OUTPUT_OFFSET,max(32,count*32),False)
            raw=np.frombuffer(bytes(self.memory.buffer[OUTPUT_OFFSET:OUTPUT_OFFSET+count*32]),'<u4').reshape(-1,8)
            local=raw[:,:3].copy().view('<f4');world=raw[:,3:6].copy().view('<f4');ids=raw[:,7]
            color=np.c_[raw[:,6]&255,(raw[:,6]>>8)&255,(raw[:,6]>>16)&255].astype(np.uint8)
            if not np.isfinite(local).all() or not np.isfinite(world).all() or (len(ids)>1 and np.any(ids[1:]<=ids[:-1])):
                raise RuntimeError('Invalid PL output geometry or point ordering')
            self.last_timings['total_ns']=time.perf_counter_ns()-began
            if self.reference_check is None:
                from .reference import golden,compare
                expected,_=golden(data,calib,capacity=n);compare(raw,expected)
                err=np.abs(raw[:,:6].copy().view('<f4').astype(float)-expected[:,:6].copy().view('<f4'))
                self.reference_check=dict(status='ACTUAL_FIRST_KEYFRAME_GEOMETRY_RGB_INDEX_PASS',
                                          points=count,max_abs_error=float(err.max()) if err.size else 0.,
                                          scope='Independent double-precision oracle using the same FP32 input ABI; no inference accuracy claim')
            return dict(local=local,world=world,rgb=color,uv=np.c_[ids%960,ids//960],source='actual_kv260_pl_point_project')
        except Exception:self.failed=True;raise

    def close(self):
        if self.failed and self.core:
            try:idle=bool(self.core.read('AP_CTRL')&4)
            except Exception:idle=False
            if not idle:raise RuntimeError('Point core may still own DDR; reset/recover the platform before releasing its XRT buffer')
        if self.core:self.core.close();self.core=None
        if self.memory:self.memory.close();self.memory=None
