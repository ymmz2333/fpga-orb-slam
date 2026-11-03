"""Exercise bounded raw video transport and failure reporting on native Linux."""
import csv
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from orb60.kv260.video_pipe import stream


@unittest.skipUnless(hasattr(os,'mkfifo'),'Native Linux FIFO gate; run on KV260')
class VideoPipeTest(unittest.TestCase):
    def exercise(self,stamp=1,shape=(720,960,3),symlink=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fifo=root/'input';os.mkfifo(fifo,0o600)
            with (root/'ids.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['source_frame_id','timestamp_ns','gray_crc']);w.writerow([0,1000000000,0])
            if symlink:
                alias=root/'alias';alias.symlink_to(fifo)
                with self.assertRaises(ValueError):stream('unused',alias,root/'ids.csv',root/'result.json')
                return
            data=bytearray()
            def read():
                with fifo.open('rb',buffering=0) as f:
                    for block in iter(lambda:f.read(65536),b''):data.extend(block)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            image=np.full(shape,17,np.uint8)
            frame=SimpleNamespace(pts=stamp,time_base=1,to_ndarray=lambda **_:image)
            class Container:
                streams=SimpleNamespace(video=[SimpleNamespace(codec_context=SimpleNamespace(thread_count=0))])
                def __enter__(self):return self
                def __exit__(self,*_):pass
                def decode(self,*_):return iter([frame])
            fake=SimpleNamespace(open=lambda _:Container())
            try:
                with patch.dict('sys.modules',{'av':fake}):
                    if stamp==0 and shape==(720,960,3):stream('unused',fifo,root/'ids.csv',root/'result.json')
                    else:
                        with self.assertRaises(ValueError):stream('unused',fifo,root/'ids.csv',root/'result.json')
            finally:reader.join(5)
            self.assertFalse(reader.is_alive(),'FIFO did not close after success/failure')
            result=json.loads((root/'result.json').read_text())
            if stamp==0 and shape==(720,960,3):
                self.assertEqual(result['status'],'ORIGINAL_VIDEO_FIFO_DRAINED')
                self.assertEqual(data,image.tobytes())
            else:self.assertEqual(result['status'],'FAILED');self.assertEqual(len(data),0)

    def test_rgb_exact_and_eof(self):self.exercise(stamp=0)
    def test_wrong_timestamp_is_failure(self):self.exercise(stamp=1)
    def test_wrong_dimensions_are_failure(self):self.exercise(stamp=0,shape=(240,320,3))
    def test_symlink_fifo_is_rejected(self):self.exercise(symlink=True)
