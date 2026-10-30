"""Offline decoder/SSH framing tests; no drone or board connections."""
import io
import json
import queue
import re
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tt_video_config import DEFAULT_BITRATE, video_settings
from tt_decode_metrics import make_decoder, DecodeMetrics
from tt_rk_bridge import HEADER, RKBridge, read_exact
from tt_latency_recording import PacketRecorder


class Fragmented(io.BytesIO):
    def read(self,size=-1):
        return super().read(min(size,2) if size>=0 else 2)


class DecodeTests(unittest.TestCase):
    def test_requested_defaults(self):
        self.assertEqual(video_settings(),('setresolution high','setbitrate 4','setfps high'))

    def test_capture_launchers_share_four_mbps_default(self):
        from tt_xbox_station import build_parser
        self.assertEqual(DEFAULT_BITRATE, 4)
        self.assertEqual(build_parser().parse_args([]).bitrate, 4)
        for name in ('run_tt_xbox.ps1', 'run_tt_video_viewer.ps1', 'run_tt_dual_preview.ps1'):
            with self.subTest(launcher=name):
                source = Path(__file__).with_name(name).read_text(encoding='utf-8')
                match = re.search(r'\[int\]\$Bitrate\s*=\s*(\d+)', source)
                self.assertIsNotNone(match)
                self.assertEqual(int(match[1]), DEFAULT_BITRATE)

    def test_all_bitrates(self):
        for value in range(6):
            self.assertEqual(video_settings(value)[1],'setbitrate '+str(value))

    def test_bad_bitrates(self):
        for value in (-1,6,'5',True,5.0):
            with self.assertRaises(ValueError):
                video_settings(value)

    def test_fragmented_pipe_read(self):
        self.assertEqual(read_exact(Fragmented(b'abcdef'),6),b'abcdef')
        self.assertIsNone(read_exact(io.BytesIO(),3))
        self.assertEqual(read_exact(io.BytesIO(),0),b'')

    def test_truncated_pipe(self):
        with self.assertRaises(EOFError):
            read_exact(Fragmented(b'abc'),4)

    def bridge(self,payload):
        bridge = RKBridge.__new__(RKBridge)
        bridge.process = SimpleNamespace(stdout=Fragmented(payload))
        bridge.lock,bridge.ready = threading.Lock(),threading.Event()
        bridge.stats,bridge.sent = {'event':'starting'},{}
        bridge.frame,bridge.received = None,0
        return bridge

    def test_clean_completion(self):
        meta = json.dumps({'event':'done','decoded':300}).encode()
        bridge = self.bridge(HEADER.pack(len(meta),0)+meta)
        bridge.read_loop()
        self.assertEqual(bridge.latest()[2]['event'],'done')

    def test_unconfirmed_eof_fails(self):
        meta = json.dumps({'event':'ready'}).encode()
        bridge = self.bridge(HEADER.pack(len(meta),0)+meta)
        bridge.read_loop()
        self.assertEqual(bridge.latest()[2]['event'],'error')

    def test_invalid_preview_length_fails(self):
        bridge = self.bridge(HEADER.pack(65537,0))
        bridge.read_loop()
        self.assertEqual(bridge.latest()[2]['event'],'error')

    def test_hardware_does_not_silently_fallback(self):
        with patch('tt_decode_metrics.HWAccel') as accel, patch('tt_decode_metrics.av.CodecContext.create') as create:
            codec = make_decoder('d3d11va')
            self.assertEqual(codec.thread_count,1)
            self.assertFalse(accel.call_args.kwargs['allow_software_fallback'])
            self.assertEqual(create.call_args.kwargs['hwaccel'],accel.return_value)
        with self.assertRaises(ValueError):
            make_decoder('guess')

    def test_bounded_metrics(self):
        metrics = DecodeMetrics('software')
        metrics.decode.extend(range(2000))
        self.assertEqual(len(metrics.decode),1800)
        self.assertFalse(metrics.snapshot()['hardware_active'])
        self.assertIn('not camera',metrics.snapshot()['definition'])

    def test_recording_retains_requested_settings(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/'clip'
            recorder = PacketRecorder()
            recorder.start(directory,'handheld',{'bitrate':5,'resolution':'high','fps':'high'})
            recorder.close()
            capture = json.loads((directory/'capture.json').read_text())
            self.assertEqual(capture['requested_settings']['bitrate'],5)


if __name__ == '__main__':
    unittest.main()
