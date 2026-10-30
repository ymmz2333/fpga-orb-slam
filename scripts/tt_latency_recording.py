"""Low-overhead encoded-packet recording and a screen timing pattern.

Packet PTS values below are synthetic association IDs, NOT camera timestamps.
They let offline replay match frames to real live decoder-ready timestamps,
even if recording started between keyframes.
"""
import json
from collections import deque
from pathlib import Path
import re
import time

import cv2
import numpy as np

START_CODE = re.compile(b'\x00\x00(?:\x00)?\x01')
DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_1000)
TARGET_WINDOW = 'TT LATENCY TARGET - point camera here'


def timing_pattern(marker_id):
    canvas = np.full((760,700,3),255,np.uint8)
    marker = cv2.aruco.generateImageMarker(DICTIONARY,marker_id,560)
    canvas[70:630,70:630] = cv2.cvtColor(marker,cv2.COLOR_GRAY2BGR)
    for text, y, scale in [('TT LATENCY RECORDING - NO FLIGHT',35,.7),
                           (f'Frame code: {marker_id:03d}',680,.85),
                           ('Keep all four marker corners visible',720,.65)]:
        cv2.putText(canvas,text,(20,y),cv2.FONT_HERSHEY_SIMPLEX,scale,(0,0,0),2)
    return canvas


class PacketRecorder:
    def __init__(self):
        self.headers = {}
        self.handles = []
        self.directory = None
        self.packet_count = self.frame_count = 0
        self.offset = 0
        self.history = deque()
        self.history_bytes = 0

    def update_headers(self,payload):
        starts = list(START_CODE.finditer(payload))
        for index, match in enumerate(starts):
            end = starts[index+1].start() if index+1<len(starts) else len(payload)
            nal = payload[match.end():end]
            if nal and nal[0]&31 in (7,8):
                self.headers[nal[0]&31] = b'\0\0\0\1'+nal

    def start(self,directory,kind='latency',metadata=None):
        self.close()
        self.kind = kind
        self.metadata = metadata or {}
        self.directory = Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        (self.directory/'codec_headers.h264').write_bytes(b''.join(self.headers[x] for x in sorted(self.headers)))
        self.raw = (self.directory/'packets.h264').open('xb');self.handles.append(self.raw)
        self.packets = (self.directory/'packets.jsonl').open('x');self.handles.append(self.packets)
        self.frames = (self.directory/'frames.jsonl').open('x');self.handles.append(self.frames)
        self.packet_count = self.frame_count = self.offset = 0
        self.started = time.perf_counter()
        # Include the previous IDR and subsequent packets so offline replay can
        # reconstruct reference pictures even when SPACE was pressed mid-GOP.
        for payload,tag,received in self.history:
            self._write_packet(payload,tag,received)

    def packet(self,payload,tag,received,keyframe=False):
        self.update_headers(payload)
        if keyframe:
            self.history.clear();self.history_bytes=0
        self.history.append((payload,tag,received));self.history_bytes+=len(payload)
        while self.history_bytes>16*1024*1024:
            self.history_bytes-=len(self.history.popleft()[0])
        if not self.handles: return
        self._write_packet(payload,tag,received)

    def _write_packet(self,payload,tag,received):
        self.raw.write(payload)
        self.packets.write(json.dumps(dict(tag=tag,offset=self.offset,bytes=len(payload),
                                           t_parser_emit=received))+'\n')
        self.offset += len(payload);self.packet_count += 1

    def frame(self,tag,ready,width,height):
        if not self.handles: return
        self.frames.write(json.dumps(dict(tag=tag,t_ready=ready,width=width,height=height))+'\n')
        self.frame_count += 1

    def close(self):
        if not self.handles: return
        for handle in self.handles: handle.close()
        self.handles = []
        result = dict(started=self.started,ended=time.perf_counter(),packets=self.packet_count,
                      decoded_frames=self.frame_count,bytes=self.offset,
                      closed=True,kind=self.kind,nominal_fps=30,
                      requested_settings=self.metadata,
                      timing_definition='PC perf_counter seconds; not camera acquisition time',
                      includes_keyframe_preroll=True,
                      tag_definition='Synthetic packet association ID; not source camera timestamp')
        (self.directory/'capture.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
