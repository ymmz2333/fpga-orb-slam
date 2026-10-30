"""Actual control/stream sockets for stop->prepare->handshake->start, no PL."""
import os,subprocess,tempfile,time,unittest
from pathlib import Path
from .offline_gate import OUT,bundle,free_port
from orb60.demo_bridge.calibration import fingerprint
from orb60.demo_bridge.protocol import command,connect,Packet,Kind,receive

class Restart(unittest.TestCase):
    def test_two_explicit_stop_start_cycles(self):
        executable=Path(os.environ.get('ORB60_TEST_BRIDGE',str(OUT/'native_direct_restart/test-bridge.exe')))
        with tempfile.TemporaryDirectory(dir=OUT) as tmp:
            root=Path(tmp);camera=bundle(root/'map');ports=[free_port() for _ in range(3)]
            with (root/'server.log').open('w') as log:
                child=subprocess.Popen([str(executable),'--serve-test',str(root/'store'),str(camera),*map(str,ports),'15'],stdout=log,stderr=log)
                def wait(predicate):
                    end=time.monotonic()+4
                    while time.monotonic()<end:
                        try:
                            s=command('127.0.0.1',ports[1],'status')
                            if predicate(s):return s
                        except OSError:pass
                        time.sleep(.02)
                    raise AssertionError('Runtime state transition timed out')
                try:
                    wait(lambda s:s['hardware_verified'])
                    for _ in range(2):
                        self.assertEqual(command('127.0.0.1',ports[1],'stop')['mode'],'STOPPED')
                        self.assertEqual(command('127.0.0.1',ports[1],'prepare')['mode'],'WAITING')
                        with connect('127.0.0.1',ports[0]) as peer:
                            peer.sendall(Packet(Kind.HELLO,body=fingerprint(camera.read_bytes()).encode()).encode())
                            self.assertEqual(receive(peer).kind,Kind.HELLO)
                            wait(lambda s:s['stream_connected'])
                            self.assertEqual(command('127.0.0.1',ports[1],'start')['mode'],'MAPPING')
                            frame=receive(peer);self.assertEqual(frame.kind,Kind.FRAME)
                            peer.sendall(Packet(Kind.ACK,frame.session,frame.frame,frame.stamp).encode())
                            command('127.0.0.1',ports[1],'stop')
                        wait(lambda s:not s['stream_connected'])
                finally:child.terminate();child.wait(timeout=5)

if __name__=='__main__':unittest.main()
