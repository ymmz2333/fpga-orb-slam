"""Transport regression fixtures; never used as demonstration scene data."""
import json
import socket
import struct
import sys
from pathlib import Path
import threading
import unittest
import time
from dense_live import DenseLiveSource
from test_viewer import fixture
from protocol import Snapshot,HEADER as FRAME_HEADER
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dense.live_protocol import encode,receive,HEADER,MAX_PAYLOAD


class DenseDeltaProtocolTests(unittest.TestCase):
    def exchange(self,data):
        a,b=socket.socketpair()
        try:
            thread=threading.Thread(target=lambda:(a.sendall(data),a.close()),daemon=True);thread.start()
            return receive(b)
        finally:a.close();b.close()

    def test_framed_delta_preserves_payload(self):
        meta=dict(event='chunk',map_id=2,keyframe_id=7,points=3)
        actual,payload=self.exchange(encode(meta,b'point-delta'))
        self.assertEqual(actual,meta);self.assertEqual(payload,b'point-delta')

    def test_corruption_and_unbounded_lengths_rejected(self):
        data=bytearray(encode(dict(event='status'),b'abc'));data[-1]^=1
        with self.assertRaises(ValueError):self.exchange(data)
        header=HEADER.pack(b'ORBDENS1',1,10,MAX_PAYLOAD+1,0)
        with self.assertRaises(ValueError):self.exchange(header)

    def test_disconnect_is_terminal_and_drops_pending_results(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        def serve():
            conn,_=listener.accept()
            with conn:conn.sendall(encode(dict(event='hello',session='test-disconnect')))
            listener.close()
        worker=threading.Thread(target=serve);worker.start()
        source=DenseLiveSource('127.0.0.1',listener.getsockname()[1]);source.start()
        source.join(3)
        self.assertFalse(source.is_alive());self.assertEqual(source.state,'ERROR')
        self.assertIsNone(source.take());self.assertEqual(source.take_chunks(),[])
        source.close();worker.join()

    def test_cpu_result_rejected_before_display(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        def serve():
            conn,_=listener.accept()
            with conn:
                conn.sendall(encode(dict(event='hello',session='test-cpu')))
                conn.sendall(encode(dict(event='frame'),fixture()))
            listener.close()
        worker=threading.Thread(target=serve);worker.start()
        source=DenseLiveSource('127.0.0.1',listener.getsockname()[1]);source.start();source.join(3)
        self.assertEqual(source.state,'ERROR');self.assertIn('CPU',source.error)
        self.assertEqual(source.received,0);self.assertIsNone(source.take());source.close();worker.join()


if __name__=='__main__':unittest.main()
