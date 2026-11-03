"""Host-only cache/command and failure-lifetime checks, without opening hardware."""
import argparse,hashlib,json,struct,threading
from pathlib import Path
import numpy as np
from .runtime import Projector,STATS_OFFSET
from .reference import MAGIC

class Memory:
    def __init__(self):self.buffer=bytearray(16*1024*1024);self.closed=False;self.syncs=[];self.address=0x100001000
    def sync(self,offset,size,to_device):self.syncs.append((offset,size,to_device))
    def close(self):self.closed=True

class Core:
    def __init__(self,memory,idle=True):self.memory=memory;self.idle=idle;self.started=False;self.closed=False;self.writes={}
    def read(self,name):
        if name=='AP_CTRL':return (4 if self.idle else 0)|(2 if self.started else 0)
        if name=='AP_RETURN':return 0
        raise AssertionError(name)
    def write(self,name,value):
        self.writes[name]=value
        if name=='AP_CTRL':
            assert self.writes['GIE']==0
            assert (STATS_OFFSET,32,True) in self.memory.syncs
            struct.pack_into('<8I',self.memory.buffer,STATS_OFFSET,self.writes['COUNT_DATA'],0,0,0,MAGIC,1,0,0)
            self.started=True
    def close(self):self.closed=True

def instance(idle=True):
    p=Projector.__new__(Projector);p.memory=Memory();p.core=Core(p.memory,idle)
    p.failed=False;p.timeout=.01;p.lock=threading.Lock();return p

def main():
    args=argparse.ArgumentParser();args.add_argument('output',type=Path);a=args.parse_args()
    if a.output.exists():raise ValueError('Fresh driver check output required')
    p=instance();memory,core=p.memory,p.core
    result=p.project(np.ones((720,960)),np.zeros((720,960,3),np.uint8),np.zeros((720,960),bool),np.eye(3),np.eye(4))
    assert not len(result['world']) and core.writes['GIE']==0
    assert core.writes['SAMPLES_DATA']>2**32 and (STATS_OFFSET,32,False) in memory.syncs
    p.close();assert memory.closed and core.closed
    p=instance(False);memory,core=p.memory,p.core;p.failed=True
    try:p.close()
    except RuntimeError:pass
    else:raise AssertionError('Busy failed core released its buffer')
    assert not memory.closed and not core.closed
    core.idle=True;p.close();assert memory.closed and core.closed
    driver=Path(__file__).with_name('runtime.py')
    report=dict(status='HOST_DRIVER_CONTRACT_PASS_NOT_HARDWARE',hardware_executed=False,
        explicit_interrupt_disable=True,cache_sync_checked=True,high_address_preserved=True,
        busy_failed_core_retains_buffer=True,idle_failed_core_cleanup=True,
        driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest())
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
