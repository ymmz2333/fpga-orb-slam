"""Compare replay transport with an independently retained physical packet."""
import json
from pathlib import Path
import socket
import threading
import unittest
import hashlib
from orb60.kv260.replay_saved import serve
from orb60.demo_bridge.protocol import Packet,Kind,receive,validate_frame

ROOT=Path(__file__).resolve().parents[3]


class TestSavedReplay(unittest.TestCase):
    def test_first_frame_matches_frozen_physical_packet(self):
        inputs=ROOT/'orb60/build/kv260_system/replay_300'
        camera=(inputs/'camera.csv').read_bytes();digest=hashlib.sha256(camera).hexdigest()
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(15)
        address=listener.getsockname();ready=threading.Event();errors=[]
        def producer():
            try:serve(listener,inputs/'capture',inputs/'video.mp4',camera,1,ready)
            except BaseException as error:errors.append(repr(error))
            finally:listener.close()
        thread=threading.Thread(target=producer);thread.start();self.assertTrue(ready.wait(10))
        try:
            with socket.create_connection(address,timeout=10) as client:
                client.sendall(Packet(Kind.HELLO,body=digest.encode()).encode());self.assertEqual(receive(client).kind,Kind.HELLO)
                frame=receive(client);validate_frame(frame)
                reference=Packet.decode((ROOT/'orb60/demo_bridge/tests/fixtures/historical_frame_0.packet').read_bytes())
                self.assertEqual((frame.frame,frame.stamp,frame.count,frame.aux,frame.body),
                                 (reference.frame,reference.stamp,reference.count,reference.aux,reference.body))
                client.sendall(Packet(Kind.ACK,frame.session,frame.frame,frame.stamp).encode())
                end=receive(client);self.assertEqual(end.kind,Kind.END)
                client.sendall(Packet(Kind.ACK,end.session,end.frame,end.stamp).encode())
        finally:thread.join(timeout=15)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
