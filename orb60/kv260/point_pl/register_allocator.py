"""Explicit metadata registration and real shared-DDR allocation; no PL reload."""
import argparse,ctypes as C,ctypes.util,hashlib,json
from pathlib import Path
from orb60.kv260.runtime import XrtWorkspace,SIZE

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--metadata',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();folder=a.metadata;proof=json.loads((folder/'BUILD.json').read_text());target=folder/'points_allocator.xclbin'
    if a.output.exists():raise ValueError('Fresh registration report required')
    if proof['status']!='ALLOCATOR_METADATA_ROUNDTRIP_PASS' or proof['scheduled_cus'] or proof['bitstream_in_xclbin']:raise ValueError('Verified BO-only metadata required')
    if hashlib.sha256(target.read_bytes()).hexdigest()!=proof['xclbin_sha256']:raise ValueError('Metadata binary changed')
    lib=C.CDLL(C.util.find_library('xrt_coreutil'))
    lib.xrtDeviceOpen.argtypes=[C.c_uint];lib.xrtDeviceOpen.restype=C.c_void_p
    lib.xrtDeviceLoadXclbinFile.argtypes=[C.c_void_p,C.c_char_p];lib.xrtDeviceLoadXclbinFile.restype=C.c_int
    lib.xrtDeviceClose.argtypes=[C.c_void_p];lib.xrtDeviceClose.restype=C.c_int
    device=lib.xrtDeviceOpen(0)
    if not device:raise RuntimeError('Native XRT device not found')
    try:
        if lib.xrtDeviceLoadXclbinFile(device,str(target.resolve()).encode()):raise RuntimeError('Allocator metadata registration failed')
    finally:lib.xrtDeviceClose(device)
    memory=XrtWorkspace()
    try:
        if memory.address+SIZE>0x80000000:raise RuntimeError('Allocated DDR lies outside verified HP2 low-DDR map')
        memory.buffer[:64]=bytes(range(64));memory.sync(0,64,True);memory.sync(0,64,False)
        if bytes(memory.buffer[:64])!=bytes(range(64)):raise RuntimeError('Allocator CPU/cache readback failed')
        report=dict(status='ACTUAL_XRT_ALLOCATOR_REGISTRATION_PASS',xclbin_sha256=proof['xclbin_sha256'],
                    physical_address=memory.address,bytes=SIZE,bitstream_in_xclbin=False,scheduled_cus=0,
                    scope='Real BO allocation/cache API; PL access tested separately; no FPGA reload')
    finally:memory.close()
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
