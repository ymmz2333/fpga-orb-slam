"""Protocol, map semantics and bounded input tests; synthetic data is test-only."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
import zlib
import cv2
import numpy as np
from protocol import HEADER,Snapshot,body_size,receive_snapshot,POINT_DTYPE,KEYFRAME_DTYPE
from model import Scene,frustum_lines,export_ply,view_points
from bridge import Bridge
from sources import Recording,LiveSource,PlayoutQueue


def fixture(index=1,map_id=0,valid=True,full=True):
    points=np.zeros(2,dtype=POINT_DTYPE);points['id']=[11,12];points['xyz']=[[1,2,3],[4,5,6]]
    keys=np.zeros(1,dtype=KEYFRAME_DTYPE);keys['id']=2;keys['twc']=np.eye(4)
    if not full:points=points[:0];keys=keys[:0]
    pose=np.eye(4);pose[0,3]=index
    meta=dict(frame_index=index,timestamp_ns=1000000000+index*33333333,map_id=map_id,state=2 if valid else 1,
              width=960,height=720,pose_twc=pose.reshape(-1).tolist(),pose_valid=valid,map_full=full,
              features=[[100.,80.,0,1]],feature_count=1,source_gray=True,source='test',processing_fps=30,
              track_ms=5,feature_wait_ms=1)
    _,jpeg=cv2.imencode('.jpg',np.zeros((720,960),np.uint8));j=json.dumps(meta).encode()
    body=j+jpeg.tobytes()+points.tobytes()+keys.tobytes()
    return HEADER.pack(b'ORBVIZ01',1,len(j),len(jpeg),len(points),len(keys),zlib.crc32(body))+body


class Tests(unittest.TestCase):
    def test_bounded_paced_playout(self):
        queue=PlayoutQueue(120,capacity=3)
        for i in range(3):queue.push(Snapshot.decode(fixture(i+1)),10+i*.01)
        self.assertIsNone(queue.take(10.119))
        self.assertEqual(queue.take(10.121).meta['frame_index'],1)
        self.assertIsNone(queue.take(10.14))
        self.assertEqual(queue.take(10.155).meta['frame_index'],2)
        for i in range(4,9):queue.push(Snapshot.decode(fixture(i)),10.2)
        self.assertEqual(len(queue.frames),3);self.assertEqual(queue.dropped,3)
        self.assertEqual([queue.take(20).meta['frame_index'] for _ in range(3)],[6,7,8])

    def test_crc_bounds_and_fragmented(self):
        data=fixture();snap=Snapshot.decode(data);self.assertEqual(snap.points['id'].tolist(),[11,12])
        bad=bytearray(data);bad[-1]^=1
        with self.assertRaises(ValueError):Snapshot.decode(bad)
        with self.assertRaises(ValueError):Snapshot.decode(data[:-1])
        with self.assertRaises(ValueError):body_size(HEADER.pack(b'ORBVIZ01',1,100,9000000,0,0,0))
        a,b=socket.socketpair()
        def send():
            with a:
                for at in range(0,len(data),71):a.sendall(data[at:at+71])
        t=threading.Thread(target=send);t.start()
        with b:self.assertEqual(receive_snapshot(b).meta['frame_index'],1)
        t.join()

    def test_map_reset_stale_invalid_and_coordinate(self):
        scene=Scene();self.assertTrue(scene.apply(Snapshot.decode(fixture())))
        self.assertFalse(scene.apply(Snapshot.decode(fixture())))
        scene.apply(Snapshot.decode(fixture(2,valid=False,full=False)));self.assertFalse(scene.pose_valid)
        self.assertEqual(len(scene.points),2)
        scene.apply(Snapshot.decode(fixture(3,full=False)));self.assertEqual(len(scene.segments),0)
        scene.apply(Snapshot.decode(fixture(4,map_id=1,valid=False,full=False)))
        self.assertEqual(len(scene.points),0);self.assertEqual(len(scene.trace),0)
        np.testing.assert_array_equal(view_points([[1,2,3]]),[[1,3,-2]])
        self.assertEqual(frustum_lines(np.eye(4)[None],1).shape,(16,3))

    def test_replay_bridge_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'frames').mkdir()
            for i in range(1,4):(path/'frames'/f'{i:08d}.orbv').write_bytes(fixture(i,full=i==1))
            recording=Recording(path);self.assertEqual(recording.nearest_map(2).meta['frame_index'],1)
            scene=Scene();scene.apply(recording.read(0));export_ply(path/'map.ply',scene)
            self.assertIn('1 2 3',(path/'map.ply').read_text())
            (path/'latest.orbv').write_bytes(fixture(3));(path/'status.json').write_text('{"state":"COMPLETED"}')
            bridge=Bridge(path,'127.0.0.1',0);thread=threading.Thread(target=bridge.serve);thread.start()
            source=LiveSource('127.0.0.1',bridge.socket.getsockname()[1]);source.start()
            import time
            deadline=time.monotonic()+3;snapshot=None
            while time.monotonic()<deadline and snapshot is None:time.sleep(.03);snapshot=source.take()
            self.assertIsNotNone(snapshot);self.assertEqual(snapshot.meta['frame_index'],3)
            source.close();bridge.stop.set();thread.join(2);self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()
