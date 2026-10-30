import os,tempfile,subprocess,time,unittest
from pathlib import Path
from .offline_gate import OUT,bundle,free_port
from orb60.demo_bridge.dense_environment import write
from orb60.demo_bridge.map_bundle import seal,upload
from orb60.demo_bridge.calibration import fingerprint
from orb60.demo_bridge.protocol import connect,command,Packet,Kind,receive

class V2Transfer(unittest.TestCase):
    def test_complete_v2_wire_transfer_includes_dense_file(self):
        exe=Path(os.environ['ORB60_TEST_BRIDGE'])
        with tempfile.TemporaryDirectory(dir=OUT) as tmp:
            root=Path(tmp);folder=root/'map';camera=bundle(folder)
            write(folder/'dense_environment.bin',[[0,0,1],[.2,0,2]],[[10,20,30],[40,50,60]],folder/'points.csv',camera)
            version=seal(folder,camera,7);ports=[free_port() for _ in range(3)]
            with (root/'server.log').open('w') as log:
                child=subprocess.Popen([str(exe),'--serve-test',str(root/'store'),str(camera),*map(str,ports),'20'],stdout=log,stderr=log)
                def wait(predicate):
                    end=time.monotonic()+5
                    while time.monotonic()<end:
                        try:
                            s=command('127.0.0.1',ports[1],'status')
                            if predicate(s):return s
                        except OSError:pass
                        time.sleep(.01)
                    raise AssertionError('Runtime did not complete expected state')
                try:
                    wait(lambda s:s['hardware_verified'])
                    with connect('127.0.0.1',ports[0]) as peer:
                        peer.sendall(Packet(Kind.HELLO,body=fingerprint(camera.read_bytes()).encode()).encode());self.assertEqual(receive(peer).kind,Kind.HELLO)
                        wait(lambda s:s['stream_connected']);command('127.0.0.1',ports[1],'start')
                        command('127.0.0.1',ports[1],'finalize')
                        while True:
                            packet=receive(peer);peer.sendall(Packet(Kind.ACK,packet.session,packet.frame,packet.stamp).encode())
                            if packet.kind==Kind.END:break
                        wait(lambda s:s['drained'])
                        upload(folder,'127.0.0.1',ports[2]);wait(lambda s:s['mode']=='LOCAL')
                    target=root/'store/versions'/version/'dense_environment.bin'
                    self.assertEqual(target.read_bytes(),(folder/'dense_environment.bin').read_bytes())
                finally:child.terminate();child.wait(timeout=5)

if __name__=='__main__':unittest.main()
