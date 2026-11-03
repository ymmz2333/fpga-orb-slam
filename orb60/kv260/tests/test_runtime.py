"""Hardware-interface contracts; these tests are explicitly not PL emulation."""
import ctypes
import struct
import unittest
from types import SimpleNamespace
from orb60.kv260.runtime import OrbFrontend,UioCore,XrtWorkspace,SIZE


class TestRuntime(unittest.TestCase):
    def test_pointer_above_four_gib_and_shifted_scalar(self):
        core=object.__new__(UioCore);core.mm=bytearray(256)
        core.abi={'offsets':{'BLURRED_DATA':0x24,'WIDTH_DATA':0x54},'widths':{'BLURRED_DATA':64,'WIDTH_DATA':32}}
        core.write('BLURRED_DATA',0x123456789abcdef0);core.write('WIDTH_DATA',960)
        self.assertEqual(struct.unpack_from('<II',core.mm,0x24),(0x9abcdef0,0x12345678))
        self.assertEqual(struct.unpack_from('<I',core.mm,0x54)[0],960)
        with self.assertRaises(ValueError):core.write('WIDTH_DATA',1<<32)
        with self.assertRaises(ValueError):core.write('BLURRED_DATA',1<<64)

    def test_cache_sync_direction_alignment_and_bounds(self):
        calls=[];memory=object.__new__(XrtWorkspace);memory.bo=17
        memory.lib=SimpleNamespace(xrtBOSync=lambda *args:calls.append(args) or 0)
        memory.sync(0x100ff8,691200,True);memory.sync(0x530ff8,64000,False)
        self.assertEqual(calls,[(17,0,691264,0x100fc0),(17,1,64064,0x530fc0)])
        with self.assertRaises(ValueError):memory.sync(SIZE-1,2,False)
        with self.assertRaises(ValueError):memory.sync(-1,64,True)
        memory.lib.xrtBOSync=lambda *args:-1
        with self.assertRaises(RuntimeError):memory.sync(0,64,False)

    def test_completion_clear_on_read_is_latched_per_core(self):
        class Core:
            def __init__(self,done_at):self.calls=0;self.done_at=done_at
            def read(self,name):
                self.calls+=1
                return 2 if self.calls==self.done_at else 0
        a,b=Core(1),Core(4);OrbFrontend(None,None,None)._wait([a,b])
        self.assertEqual((a.calls,b.calls),(1,4))

    def test_timeout_latches_failure_and_prevents_reuse(self):
        class Memory:
            address=0x100000000
            buffer=bytearray(SIZE)
            def sync(self,*args):pass
        writes=[]
        core=SimpleNamespace(read=lambda name:4,write=lambda *args:writes.append(args))
        frontend=OrbFrontend(Memory(),core,core,timeout=0)
        with self.assertRaises(TimeoutError):frontend.run(bytes(960*720))
        self.assertTrue(frontend.failed);before=len(writes)
        with self.assertRaises(RuntimeError):frontend.run(bytes(960*720))
        self.assertEqual(len(writes),before)
        self.assertIn(('IMAGE_R_DATA',0x100100ff8),writes)


if __name__=='__main__':unittest.main()
