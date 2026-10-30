"""Color side-channel identity, exact crop, bounded stalls; no hardware claims."""
import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
import cv2
import numpy as np
from orb60.demo_bridge.protocol import Packet,Kind,connect,receive
from orb60.demo_bridge.dense_camera import decode_color, GroupedChunks, POINT
from .offline_gate import ROOT,OUT,NATIVE,free_port


class Color(unittest.TestCase):
    def test_incremental_group_fuses_in_anchor_coordinates_and_updates_one_block(self):
        class Server:
            state='RUNNING'
            def __init__(self):self.sent=[]
            def publish(self,meta,payload):self.sent.append((meta,payload))
        with tempfile.TemporaryDirectory(dir=OUT) as directory:
            server=Server();group=GroupedChunks(server,directory)
            for i in range(9):
                pose=np.eye(4);pose[0,3]=i*.1
                # Keep the synthetic point away from a voxel boundary; float32
                # input roundoff on that boundary legitimately occupies two cells.
                points=np.empty(1,dtype=POINT);points['xyz']=[[1.023-i*.1,0,2.023]];points['rgb']=[[255,0,0]]
                group.publish(dict(map_id=1,keyframe_id=-i-1,source_frame_index=i,twc=pose.tolist(),voxel_edge=.05),points.tobytes())
            self.assertEqual([v[0]['keyframe_id'] for v in server.sent],[-1]*8+[-9])
            self.assertEqual([v[0]['revision'] for v in server.sent],list(range(1,9))+[1])
            final=np.frombuffer(server.sent[7][1],dtype=POINT)
            np.testing.assert_allclose(final['xyz'],[[1.023,0,2.023]],atol=1e-6)
            np.testing.assert_array_equal(final['rgb'],[[255,0,0]])
            self.assertEqual(group.counts(),(2,2))

    def test_exact_source_crop_and_identity_rejection(self):
        data=(ROOT/'zynq7015_demo/tests/fixtures/camera/1280x720_RGB_2.jpg').read_bytes()
        packet=Packet(Kind.COLOR,77,12,123456789,aux=987,body=data)
        meta=dict(session=77,source_frame_id=12,timestamp_ns=123456789,gray_crc=987)
        actual=decode_color(packet,meta)
        full=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(actual,full[:,160:1120])
        self.assertEqual(actual.shape,(720,960,3))
        for field in ('session','source_frame_id','timestamp_ns','gray_crc'):
            bad=dict(meta);bad[field]+=1
            with self.assertRaisesRegex(ValueError,'identity'):decode_color(packet,bad)
        with tempfile.TemporaryDirectory(dir=OUT) as d:
            src,dst=Path(d)/'in',Path(d)/'out'
            src.write_bytes(packet.encode());subprocess.run([NATIVE,'--wire',src,dst],check=True,timeout=10)
            self.assertEqual(src.read_bytes(),dst.read_bytes())

    def test_native_latest_only_queue_does_not_block_producer(self):
        port=free_port();jpeg=ROOT/'zynq7015_demo/tests/fixtures/camera/1280x720_RGB_2.jpg'
        child=subprocess.Popen([NATIVE,'--serve-color-test',str(port),jpeg,'a'*64],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(.2)
            with connect('127.0.0.1',port,5) as sock:
                sock.sendall(Packet(Kind.HELLO,body=b'a'*64).encode())
                self.assertEqual(receive(sock).kind,Kind.HELLO)
                first=receive(sock);self.assertEqual(first.kind,Kind.COLOR)
                time.sleep(.1) # Reader stalls; source keeps publishing.
            stdout,stderr=child.communicate(timeout=6)
            self.assertEqual(child.returncode,0,stderr)
            report=json.loads(stdout)
            self.assertEqual(report['pending_capacity'],1)
            self.assertGreater(report['dropped'],0)
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=5)


if __name__=='__main__':unittest.main()
