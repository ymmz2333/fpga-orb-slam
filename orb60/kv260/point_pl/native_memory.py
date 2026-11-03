"""Explicit official xlnx_dpu DMA allocator for the native Vivado platform.

IOCTL ABI: linux-xlnx b0c1be301e78c320df8c4d93b18393bfd7fd4e9d.
Only maps this object's own allocation; never /dev/mem or a fixed DDR address.
Create before starting VART and free after its worker exits: the retained vendor
driver's global allocation list is not designed for concurrent alloc/free.
"""
import fcntl,mmap,os,struct
from orb60.kv260.runtime import SIZE

class NativeDpuWorkspace:
    def __init__(self):
        self.fd=None;self.mm=None;self.address=None;self.capacity=0
        if struct.calcsize('P')!=8:raise RuntimeError('Native aarch64 64-bit DPU IOCTL ABI required')
        try:
            self.fd=os.open('/dev/dpu',os.O_RDWR|os.O_CLOEXEC)
            request=bytearray(struct.pack('<QQQ',SIZE,0,0));fcntl.ioctl(self.fd,0xc0084401,request,True)
            _,self.address,self.capacity=struct.unpack('<QQQ',request)
            if not self.address or self.address%4096 or self.capacity!=SIZE or self.address+SIZE>0x80000000:
                raise RuntimeError('Native DMA allocation is outside matched HP2 low-DDR map')
            self.mm=mmap.mmap(self.fd,SIZE,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE,offset=self.address)
            self.buffer=memoryview(self.mm)
        except Exception:self.close();raise

    def sync(self,offset,size,to_device):
        if offset<0 or size<0 or offset+size>SIZE:raise ValueError('DMA sync outside owned workspace')
        begin=offset&~63;end=(offset+size+63)&~63
        request=bytearray(struct.pack('<QQi4x',self.address+begin,end-begin,0 if to_device else 1))
        fcntl.ioctl(self.fd,0xc0084403,request,True)

    def close(self):
        if hasattr(self,'buffer'):self.buffer.release();del self.buffer
        if self.mm is not None:self.mm.close();self.mm=None
        if self.fd is not None:
            try:
                if self.address is not None:
                    fcntl.ioctl(self.fd,0xc0084402,bytearray(struct.pack('<QQ',self.address,self.capacity)),True);self.address=None
            finally:os.close(self.fd);self.fd=None

def allocate(backend,index=0):
    if backend=='native-dpu':return NativeDpuWorkspace()
    if backend=='xrt':
        from orb60.kv260.runtime import XrtWorkspace
        return XrtWorkspace(index)
    raise ValueError('Explicit native-dpu or xrt workspace backend required')
