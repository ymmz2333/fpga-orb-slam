"""Bounded local RGB/gray association created before PL processes that exact frame."""
import hashlib
import json
from pathlib import Path
import zlib
import cv2
import numpy as np
from .dense_fusion import save


class FrameStore:
    def __init__(self,folder,capacity=32):
        if not 2<=capacity<=128:raise ValueError('Invalid frame cache capacity')
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.capacity=capacity;self.last=-1

    def publish(self,frame,timestamp_ns,bgr,gray):
        if frame<=self.last or not isinstance(timestamp_ns,int) or timestamp_ns<=0:raise ValueError('Monotonic integer frame identity required')
        if bgr.shape!=(720,960,3) or bgr.dtype!=np.uint8 or gray.shape!=(720,960) or gray.dtype!=np.uint8:raise ValueError('Working RGB/gray dimensions mismatch')
        raw=np.ascontiguousarray(gray).tobytes();path=self.folder/('f%d.png'%frame)
        if path.exists():raise ValueError('RGB frame already exists')
        if not cv2.imwrite(str(path),bgr):raise IOError('Cannot save paired RGB')
        record={'source_frame_id':frame,'timestamp_ns':timestamp_ns,'gray_crc':zlib.crc32(raw),'gray_sha256':hashlib.sha256(raw).hexdigest(),
                'rgb':path.name,'rgb_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        save(path.with_suffix('.json'),record);self.last=frame
        files=sorted(self.folder.glob('f*.json'),key=lambda p:int(p.stem[1:]))
        for old in files[:-self.capacity]:old.with_suffix('.png').unlink(missing_ok=True);old.unlink()
        return record

    def read(self,meta):
        record=json.loads((self.folder/('f%d.json'%meta['source_frame_id'])).read_text(encoding='utf-8'))
        if any(record[k]!=meta[k] for k in ('source_frame_id','timestamp_ns','gray_crc')):raise ValueError('RGB/PS-pose identity mismatch')
        path=self.folder/record['rgb']
        if path.resolve().parent!=self.folder.resolve() or hashlib.sha256(path.read_bytes()).hexdigest()!=record['rgb_sha256']:raise ValueError('RGB file path/hash mismatch')
        bgr=cv2.imread(str(path))
        if bgr is None or bgr.shape!=(720,960,3):raise ValueError('Corrupted RGB cache')
        return bgr
