"""KV260 ORB runtime: XRT-owned DMA buffer, generated 64-bit ABI and UIO control.

No /dev/mem, fixed physical DDR reservation, CPU ORB, or automatic PL loading.
Requires the matching integrated platform and explicit UIO paths.
"""
import ctypes as C
import ctypes.util
import mmap
from pathlib import Path
import struct
import time

WIDTHS=(960,800,667,556,463,386,322,268)
HEIGHTS=(720,600,500,417,347,289,241,201)
BUDGETS=(217,181,151,126,105,87,73,60)
RAWS=(0x100ff8,0x1b0ff8,0x260ff8)
BLURS=(0x310ff8,0x3c0ff8)
FEATURES=0x530ff8
SIZE=16*1024*1024


class XrtWorkspace:
    def __init__(self,index=0):
        self.device=None;self.bo=None
        name=ctypes.util.find_library('xrt_coreutil')
        if not name:raise RuntimeError('XRT coreutil is absent; no allocator fallback')
        self.lib=C.CDLL(name)
        signatures={'xrtDeviceOpen':([C.c_uint],C.c_void_p),'xrtDeviceClose':([C.c_void_p],C.c_int),
                    'xrtBOAlloc':([C.c_void_p,C.c_size_t,C.c_uint64,C.c_uint],C.c_void_p),
                    'xrtBOMap':([C.c_void_p],C.c_void_p),'xrtBOAddress':([C.c_void_p],C.c_uint64),
                    'xrtBOSync':([C.c_void_p,C.c_int,C.c_size_t,C.c_size_t],C.c_int),
                    'xrtBOFree':([C.c_void_p],C.c_int)}
        for key,(args,result) in signatures.items():
            fn=getattr(self.lib,key);fn.argtypes=args;fn.restype=result
        try:
            self.device=self.lib.xrtDeviceOpen(index)
            if not self.device:raise RuntimeError('XRT device unavailable; check zocl/platform')
            self.bo=self.lib.xrtBOAlloc(self.device,SIZE,0,0)
            if not self.bo:raise RuntimeError('XRT contiguous workspace allocation failed')
            self.address=int(self.lib.xrtBOAddress(self.bo));pointer=self.lib.xrtBOMap(self.bo)
            if self.address in (0,(1<<64)-1) or not pointer or self.address+SIZE>1<<64:
                raise RuntimeError('Invalid XRT buffer address/map')
            self.buffer=memoryview((C.c_ubyte*SIZE).from_address(pointer)).cast('B')
        except Exception:self.close();raise

    def sync(self,offset,size,to_device):
        if offset<0 or size<0 or offset+size>SIZE:raise ValueError('DMA sync range outside workspace')
        begin=offset&~63;end=(offset+size+63)&~63
        if self.lib.xrtBOSync(self.bo,0 if to_device else 1,end-begin,begin):
            raise RuntimeError('XRT cache synchronization failed')

    def close(self):
        if hasattr(self,'buffer'):self.buffer.release();del self.buffer
        if self.bo:self.lib.xrtBOFree(self.bo);self.bo=None
        if self.device:self.lib.xrtDeviceClose(self.device);self.device=None


class UioCore:
    def __init__(self,path,expected_name,expected_address,abi):
        import fcntl
        node=Path('/sys/class/uio')/Path(path).name
        if (node/'name').read_text().strip()!=expected_name:raise ValueError('UIO core identity mismatch')
        base=node/'maps/map0'
        if int((base/'addr').read_text(),0)!=expected_address or int((base/'offset').read_text(),0)!=0:
            raise ValueError('UIO control address mismatch')
        self.file=open(path,'r+b',buffering=0)
        try:
            fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.mm=mmap.mmap(self.file.fileno(),int((base/'size').read_text(),0),flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)
        except Exception:self.file.close();raise
        self.abi=abi

    def write(self,name,value):
        width=self.abi['widths'].get(name,32);offset=self.abi['offsets'][name]
        if value<0 or value>=1<<width:raise ValueError(f'{name} does not fit {width} bits')
        struct.pack_into('<I',self.mm,offset,value&0xffffffff)
        if width==64:struct.pack_into('<I',self.mm,offset+4,value>>32)

    def read(self,name):return struct.unpack_from('<I',self.mm,self.abi['offsets'][name])[0]
    def close(self):self.mm.close();self.file.close()


class OrbFrontend:
    def __init__(self,memory,layer,descriptor,timeout=2.):
        self.memory=memory;self.layer=layer;self.descriptor=descriptor;self.timeout=timeout;self.failed=False;self.ever_started=False

    def _start(self,core,pointers,controls):
        if not core.read('AP_CTRL')&4:raise RuntimeError('HLS core is not idle')
        for name,offset in pointers.items():core.write(name+'_DATA',self.memory.address+offset)
        for name,value in controls.items():core.write(name+'_DATA',value)
        core.write('AP_CTRL',1)
        self.ever_started=True

    def _wait(self,cores):
        pending=list(cores);deadline=time.monotonic()+self.timeout
        while pending:
            pending=[core for core in pending if not core.read('AP_CTRL')&2]
            if time.monotonic()>deadline:raise TimeoutError('ORB hardware timeout; platform reset/reload required')

    def _image(self,l):
        self._start(self.layer,dict(IMAGE_R=RAWS[l%3],BLURRED=BLURS[l%2],RESIZED=RAWS[(l+1)%3],SELECTED=0x470ff8+0x4000*l,RESULT=0x500fc0+0x80*l,STATS=0x510fc0+0x80*l),
                    dict(LEVEL=l,BUDGET=BUDGETS[l],HIGH_THRESHOLD=20,LOW_THRESHOLD=7,DUAL_THRESHOLD=1,SELECTED_CAPACITY=1000))

    def _count(self,l):
        summary=0x500fc0+0x80*l;stats=0x510fc0+0x80*l
        self.memory.sync(summary,64,False);self.memory.sync(stats,64,False)
        s=struct.unpack_from('<16I',self.memory.buffer,summary);t=struct.unpack_from('<16I',self.memory.buffer,stats)
        returned=self.layer.read('AP_RETURN')
        if returned or s[:2]!=(0x20000,0) or s[3]>min(BUDGETS[l],256) or t[:5]!=(0x600003,0,l,WIDTHS[l],HEIGHTS[l]) or not t[11]:
            raise RuntimeError(f'Layer result/stats ABI mismatch: level={l}, return={returned}, summary={s}, stats={t}')
        return s[3]

    def _descriptor(self,l,count,offset):
        self._start(self.descriptor,dict(RAW=RAWS[l%3],BLURRED=BLURS[l%2],POINTS=0x470ff8+0x4000*l,FEATURES=FEATURES,STATS=0x520fc0+0x80*l),
                    dict(WIDTH=WIDTHS[l],HEIGHT=HEIGHTS[l],COUNT=count,LEVEL=l,FRAME_OFFSET=offset,CAPACITY=1000))

    def run(self,gray):
        if self.failed:raise RuntimeError('Previous hardware failure; refuse reuse until platform reset/reload')
        gray=memoryview(gray).cast('B')
        if gray.nbytes!=960*720:raise ValueError('Exactly 960x720 uint8 working gray bytes required')
        started=time.perf_counter_ns()
        try:
            self.memory.buffer[RAWS[0]:RAWS[0]+len(gray)]=gray
            self.memory.sync(RAWS[0],len(gray),True)
            for l in range(8):
                for base in (0x500fc0,0x510fc0,0x520fc0):
                    offset=base+0x80*l;self.memory.buffer[offset:offset+64]=b'\xa5'*64;self.memory.sync(offset,64,True)
            copied=time.perf_counter_ns()-started;core_start=time.perf_counter_ns()
            counts=[];offsets=[];total=0
            self._image(0);self._wait([self.layer]);count=self._count(0)
            for l in range(8):
                offsets.append(total);counts.append(count)
                self._descriptor(l,count,total);total+=count
                if total>1000:raise RuntimeError('ORB total feature budget exceeded')
                if l<7:self._image(l+1)
                self._wait([self.descriptor,self.layer] if l<7 else [self.descriptor])
                offset=0x520fc0+0x80*l;self.memory.sync(offset,64,False)
                d=struct.unpack_from('<16I',self.memory.buffer,offset)
                if self.descriptor.read('AP_RETURN') or d[:6]!=(0x600002,0,l,count,count,offsets[-1]) or d[8]!=count*16 or d[9]!=count*64 or not d[10]:
                    raise RuntimeError('Descriptor completion ABI mismatch')
                if l<7:count=self._count(l+1)
            ns=time.perf_counter_ns()-core_start
            self.memory.sync(FEATURES,total*64,False)
            metadata=bytearray(128);struct.pack_into('<16I',metadata,0,*counts,*offsets);struct.pack_into('<QQ',metadata,64,ns,copied)
            records=bytes(self.memory.buffer[FEATURES:FEATURES+total*64]);stats=bytearray()
            for l in range(8):
                stats+=self.memory.buffer[0x510fc0+0x80*l:0x511000+0x80*l]
                stats+=self.memory.buffer[0x520fc0+0x80*l:0x521000+0x80*l]
            return bytes(metadata)+records+stats,total
        except Exception:self.failed=True;raise
