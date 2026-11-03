"""UI snapshots from actual fixed-map ACKs; visualization never changes geometry."""
import csv
import json
from pathlib import Path
import time
import threading
import zlib
import cv2
import numpy as np
from orb60.viewer.protocol import HEADER, POINT_DTYPE, KEYFRAME_DTYPE, Snapshot
from .dense_fusion import save


class LocalTelemetry:
    def __init__(self, bundle, folder):
        self.bundle=Path(bundle);self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        meta=json.loads((self.bundle/'bundle.json').read_text());self.map_id=meta['map']['map_id']
        def rows(name):
            with (self.bundle/'export'/name).open(newline='') as f:return list(csv.DictReader(f))
        points=rows('points.csv');keys=rows('keyframes.csv')
        self.points=np.empty(len(points),POINT_DTYPE)
        for i,row in enumerate(points):self.points[i]=(int(row['point_id']),[float(row[k]) for k in ('x','y','z')])
        # Preview cap only; the PS locator retains the complete sealed map.
        if len(self.points)>20000:self.points=self.points[::(len(self.points)+19999)//20000]
        self.keys=np.empty(len(keys),KEYFRAME_DTYPE)
        for i,row in enumerate(keys):self.keys[i]=(int(row['keyframe_id']),np.array([float(row[f'twc_{r}{c}']) for r in range(4) for c in range(4)]).reshape(4,4))
        self.previous=None;self.previous_frame=None;self.written=0
        save(self.folder/'status.json',{'state':'RUNNING','mode':'fixed_map_localization'})

    def publish(self, packet, ack, gray, bgr=None):
        state=json.loads(ack.body)
        if (state['source_frame_id'],state['timestamp_ns'])!=(packet.frame,packet.stamp) or state['features']!=packet.count:
            raise ValueError('Fixed-map ACK payload identity/count mismatch')
        if state['mapping'] or state['cpu_orb_calls']!=0:raise ValueError('Unexpected mapping/CPU ORB in localizer')
        if gray.shape!=(720,960) or gray.dtype!=np.uint8 or zlib.crc32(gray.tobytes())!=packet.aux:
            raise ValueError('Localization display gray identity mismatch')
        if bgr is not None and (bgr.shape!=(720,960,3) or bgr.dtype!=np.uint8 or not np.array_equal(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY),gray)):
            raise ValueError('Localization color preview differs from physical frame')
        records=np.frombuffer(packet.body,dtype='<u4',offset=960*720+128,count=packet.count*16).reshape(-1,16)
        scales=np.ones(8,np.float32)
        for i in range(1,8):scales[i]=scales[i-1]*np.float32(1.2)
        features=[]
        for record in records:
            level=int(record[3])
            if not 0<=level<8:raise ValueError('Invalid display octave')
            features.append([float(np.float32(record[0])*scales[level]),float(np.float32(record[1])*scales[level]),level,0])
        now=time.monotonic_ns()
        fps=(packet.frame-self.previous_frame)*1e9/(now-self.previous) if self.previous is not None and now>self.previous else 0.
        meta=dict(schema=1,frame_index=packet.frame,timestamp_ns=packet.stamp,map_id=self.map_id,
                  state=2 if state['pose_valid'] else 3,width=960,height=720,source_gray=bgr is None,
                  source='fpga',map_full=True,raw_gray_crc=packet.aux,pose_valid=state['pose_valid'],
                  processing_fps=fps,track_ms=state['track_ms'],feature_wait_ms=0,decode_ms=0,
                  feature_count=packet.count,cpu_orb_calls=0,display_replaced=0,pose_twc=state['pose_twc'],
                  features=features,mode='fixed_map_localization',matches=state['matches'],inliers=state['inliers'])
        ok,jpeg=cv2.imencode('.jpg',gray if bgr is None else bgr,[cv2.IMWRITE_JPEG_QUALITY,80])
        if not ok:raise ValueError('Localization preview JPEG encode failed')
        encoded=json.dumps(meta,allow_nan=False,separators=(',',':')).encode()
        body=encoded+jpeg.tobytes()+self.points.tobytes()+self.keys.tobytes()
        wire=HEADER.pack(b'ORBVIZ01',1,len(encoded),len(jpeg),len(self.points),len(self.keys),zlib.crc32(body))+body
        Snapshot.decode(wire)
        temporary=self.folder/'latest.orbv.part';temporary.write_bytes(wire);temporary.replace(self.folder/'latest.orbv')
        self.previous,self.previous_frame=now,packet.frame
        self.written+=1

    def finish(self,success):
        save(self.folder/'status.json',dict(state='COMPLETED' if success else 'ERROR',written=self.written,mode='fixed_map_localization'))


class LatestLocalizationTelemetry:
    """Bounded preview worker; localization consumes every input frame."""
    def __init__(self,telemetry):
        self.telemetry=telemetry;self.folder=telemetry.folder
        self.condition=threading.Condition();self.pending=None;self.closing=False;self.error=None;self.replaced=0
        self.worker=threading.Thread(target=self.work,daemon=True);self.worker.start()

    def publish(self,packet,ack,gray,bgr=None):
        with self.condition:
            if self.error:raise RuntimeError('Localization preview failed: '+self.error)
            if self.closing:raise RuntimeError('Localization preview is closed')
            if self.pending is not None:self.replaced+=1
            # Producer creates fresh arrays for each decoded frame and never
            # mutates them. Ownership lasts until this bounded item is consumed.
            self.pending=(packet,ack,gray,bgr);self.condition.notify_all()

    def work(self):
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.pending is not None or self.closing)
                    if self.pending is None:return
                    value=self.pending;self.pending=None
                self.telemetry.publish(*value)
        except BaseException as error:
            with self.condition:self.error=repr(error);self.condition.notify_all()

    def finish(self,success):
        with self.condition:self.closing=True;self.condition.notify_all()
        self.worker.join(timeout=20)
        if self.worker.is_alive():raise TimeoutError('Localization preview did not drain')
        self.telemetry.finish(success and not self.error)
        if self.error:raise RuntimeError('Localization preview failed: '+self.error)
