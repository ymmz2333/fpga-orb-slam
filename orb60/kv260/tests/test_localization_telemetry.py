import csv
import json
import zlib
import cv2
import numpy as np
import pytest
import threading
from orb60.demo_bridge.protocol import Packet,Kind
from orb60.viewer.protocol import Snapshot
from orb60.kv260.localization_telemetry import LocalTelemetry
from orb60.kv260.localization_telemetry import LatestLocalizationTelemetry


def fixture(tmp_path):
    bundle=tmp_path/'bundle';(bundle/'export').mkdir(parents=True)
    (bundle/'bundle.json').write_text(json.dumps({'map':{'map_id':4}}))
    (bundle/'export/points.csv').write_text('point_id,x,y,z\n1,0,0,1\n')
    keys=['keyframe_id']+['twc_%d%d'%(r,c) for r in range(4) for c in range(4)]
    with (bundle/'export/keyframes.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(keys);writer.writerow([1]+np.eye(4).ravel().tolist())
    bgr=np.zeros((720,960,3),np.uint8);bgr[:]=[30,60,120];gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
    body=gray.tobytes()+bytes(128+1024)
    packet=Packet(Kind.FRAME,1,0,123456789000000001,0,zlib.crc32(gray.tobytes()),0,body)
    state=dict(source_frame_id=0,timestamp_ns=packet.stamp,features=0,mapping=False,cpu_orb_calls=0,pose_valid=True,
               pose_twc=np.eye(4).ravel().tolist(),track_ms=1.,matches=0,inliers=0)
    ack=Packet(Kind.ACK,1,0,packet.stamp,body=json.dumps(state).encode())
    return LocalTelemetry(bundle,tmp_path/'telemetry'),packet,ack,gray,bgr


def test_localization_uses_paired_color_and_original_integer_clock(tmp_path):
    telemetry,packet,ack,gray,bgr=fixture(tmp_path);telemetry.publish(packet,ack,gray,bgr=bgr)
    value=Snapshot.decode((telemetry.folder/'latest.orbv').read_bytes())
    assert not value.meta['source_gray'] and value.meta['timestamp_ns']==packet.stamp
    assert value.meta['mode']=='fixed_map_localization' and value.meta['map_id']==4


def test_wrong_color_or_gray_is_rejected(tmp_path):
    telemetry,packet,ack,gray,bgr=fixture(tmp_path)
    with pytest.raises(ValueError):telemetry.publish(packet,ack,gray,bgr=np.zeros_like(bgr))
    with pytest.raises(ValueError):telemetry.publish(packet,ack,np.zeros_like(gray))


def test_preview_queue_is_bounded_and_drains_final_frame(tmp_path):
    entered=threading.Event();release=threading.Event();seen=[]
    class Preview:
        folder=tmp_path
        def publish(self,packet,*args):
            if packet==1:entered.set();assert release.wait(3)
            seen.append(packet)
        def finish(self,success):assert success
    worker=LatestLocalizationTelemetry(Preview())
    worker.publish(1,None,None);assert entered.wait(3)
    worker.publish(2,None,None);worker.publish(3,None,None)
    release.set();worker.finish(True)
    assert seen==[1,3] and worker.replaced==1


def test_preview_failure_is_reported_on_drain(tmp_path):
    class Preview:
        folder=tmp_path
        def publish(self,*args):raise ValueError('Bad color identity')
        def finish(self,success):assert not success
    worker=LatestLocalizationTelemetry(Preview());worker.publish(1,None,None)
    with pytest.raises(RuntimeError,match='Bad color identity'):worker.finish(True)
