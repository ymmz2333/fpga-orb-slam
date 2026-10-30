"""Offline synthetic H.264 recording tests. No aircraft, network or flight."""
from fractions import Fraction
import json
import multiprocessing as mp
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

import av
import numpy as np

from tt_latency_recording import PacketRecorder
from tt_video_capture import CaptureControls, RecorderSink, export_mp4


def encoded_packets(count=60,bframes=0,width=160,height=96):
    encoder = av.CodecContext.create('libx264','w')
    encoder.width, encoder.height = width, height
    encoder.pix_fmt = 'yuv420p'
    encoder.time_base = Fraction(1,30)
    encoder.framerate = Fraction(30)
    encoder.options = {'preset':'ultrafast','tune':'zerolatency','crf':'18',
                       'x264-params':f'keyint=30:min-keyint=30:scenecut=0:bframes={bframes}'}
    result = []
    for index in range(count):
        image = np.full((height,width,3),index*3%255,np.uint8)
        image[:,index%120:index%120+20,1] = 255
        frame = av.VideoFrame.from_ndarray(image,format='bgr24')
        frame.pts = index
        result.extend(encoder.encode(frame))
    result.extend(encoder.encode(None))
    return result


def populate(recorder, directory, packets, start=10, end=45):
    decoder = av.CodecContext.create('h264','r')
    expected = []
    for index, packet in enumerate(packets[:end]):
        if index == start:
            recorder.start(directory,'handheld')
        # Sequence tags model the real receiver's parser IDs, not camera time.
        tag = index+1
        payload = bytes(packet)
        recorder.packet(payload,tag,100+index/30,packet.is_keyframe)
        incoming = av.Packet(payload)
        incoming.pts = incoming.dts = tag
        for frame in decoder.decode(incoming):
            expected.append(frame.to_ndarray(format='gray'))
            recorder.frame(frame.pts,100+index/30+.005,frame.width,frame.height)
    recorder.close()
    return expected


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = encoded_packets()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_mid_gop_mp4_matches_original_decoded_frames(self):
        directory = self.root/'handheld'
        expected = populate(PacketRecorder(),directory,self.packets)
        result = export_mp4(directory)
        self.assertFalse(result['reencoded'])
        with av.open(result['file']) as video:
            self.assertEqual((video.streams.video[0].width,video.streams.video[0].height),(160,96))
            self.assertEqual(video.streams.video[0].average_rate,30)
            frames = list(video.decode(video=0))
            self.assertEqual(len(frames),45)
            for actual, reference in zip(frames,expected):
                np.testing.assert_array_equal(actual.to_ndarray(format='gray'),reference)
            self.assertAlmostEqual(float(video.streams.video[0].duration*video.streams.video[0].time_base),1.5)
        capture = json.loads((directory/'capture.json').read_text())
        self.assertTrue(capture['closed'])
        self.assertEqual(capture['kind'],'handheld')
        rows = [json.loads(line) for line in (directory/'frames.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),35)
        self.assertEqual(rows[0]['tag'],11)
        self.assertIn('PC',capture['timing_definition'])

    def test_multiple_clips_and_finally_close(self):
        reports = queue.Queue()
        sink = RecorderSink(reports)
        for name in ('flight1','flight2'):
            populate(sink,self.root/name,self.packets,start=0,end=20)
            export_mp4(self.root/name)
        self.assertEqual([reports.get()['event'] for _ in range(4)],
                         ['started','closed','started','closed'])
        self.assertEqual([p.name for p in self.root.iterdir()],['flight1','flight2'])
        sink.close()
        self.assertTrue(reports.empty())

    def test_empty_capture_preserved_but_not_claimed_playable(self):
        directory = self.root/'empty'
        recorder = PacketRecorder()
        recorder.start(directory,'flight')
        recorder.close()
        with self.assertRaises(ValueError):
            export_mp4(directory)
        self.assertFalse((directory/'video.mp4').exists())
        self.assertTrue((directory/'capture.json').exists())

    def test_export_refuses_overwrite(self):
        directory = self.root/'clip'
        populate(PacketRecorder(),directory,self.packets)
        result = export_mp4(directory)
        before = Path(result['file']).read_bytes()
        with self.assertRaises(FileExistsError):
            export_mp4(directory)
        self.assertEqual(Path(result['file']).read_bytes(),before)

    def test_recording_longer_than_latency_test_limit(self):
        packets = encoded_packets(600)
        directory = self.root/'long'
        populate(PacketRecorder(),directory,packets,start=0,end=600)
        result = export_mp4(directory)
        self.assertEqual(result['packets'],600)
        self.assertEqual(result['duration_s'],20)

    def test_720p_resolution_is_not_gui_preview_resolution(self):
        directory = self.root/'720p'
        expected = populate(PacketRecorder(),directory,
                            encoded_packets(8,width=960,height=720),start=0,end=8)
        result = export_mp4(directory)
        with av.open(result['file']) as video:
            frames = list(video.decode(video=0))
            self.assertEqual((frames[0].width,frames[0].height),(960,720))
            self.assertEqual(len(frames),8)
            np.testing.assert_array_equal(frames[-1].to_ndarray(format='gray'),expected[-1])

    def test_b_frame_input_is_not_given_incorrect_pts(self):
        directory = self.root/'reordered'
        populate(PacketRecorder(),directory,encoded_packets(bframes=2))
        before = (directory/'packets.h264').read_bytes()
        with self.assertRaisesRegex(ValueError,'B-frame'):
            export_mp4(directory)
        self.assertFalse((directory/'video.mp4').exists())
        self.assertEqual((directory/'packets.h264').read_bytes(),before)

    def test_disk_failure_does_not_escape_to_receiver(self):
        reports = queue.Queue()
        sink = RecorderSink(reports)
        sink.start(self.root/'clip','flight')
        reports.get()
        with patch.object(sink.recorder,'_write_packet',side_effect=OSError('disk full')):
            sink.packet(bytes(self.packets[0]),1,100,True)
        self.assertEqual(reports.get()['event'],'record_error')
        # Receiver can continue decoding, and a later new recording can work.
        sink.packet(bytes(self.packets[1]),2,101,False)
        sink.start(self.root/'next','handheld')
        self.assertEqual(reports.get()['event'],'started')
        sink.close()

    def test_start_failure_is_reported(self):
        reports = queue.Queue()
        sink = RecorderSink(reports)
        with patch.object(sink.recorder,'start',side_effect=PermissionError('denied')):
            sink.start(self.root/'clip','flight')
        row = reports.get()
        self.assertEqual(row['event'],'record_error')
        self.assertEqual(row['directory'],str(self.root/'clip'))
        self.assertTrue(reports.empty())

    def test_manual_controls_ack_stop_and_background_export(self):
        ctx = mp.get_context('spawn')
        commands, reports = queue.Queue(), queue.Queue()
        controls = CaptureControls(ctx,commands,reports,self.root,'flight')
        controls.toggle(False)
        self.assertTrue(commands.empty())
        controls.toggle(True)
        start = commands.get()
        self.assertEqual(start['kind'],'flight')
        self.assertEqual(controls.state,'STARTING')
        sink = RecorderSink()
        populate(sink,start['directory'],self.packets,start=0,end=20)
        reports.put(dict(event='started',directory=start['directory'],kind='flight'))
        controls.poll()
        self.assertEqual(controls.state,'RECORDING')
        controls.toggle()
        self.assertEqual(commands.get()['action'],'stop')
        self.assertEqual(controls.state,'STOPPING')
        controls.toggle()
        self.assertTrue(commands.empty())
        # Swap back to a spawn-compatible queue for the real export process.
        controls.reports = ctx.Queue()
        controls.reports.put(dict(event='closed',directory=start['directory'],kind='flight'))
        deadline = time.monotonic()+5
        while controls.active is not None and time.monotonic()<deadline:
            controls.poll()
            time.sleep(.01)
        controls.finish()
        self.assertEqual(controls.state,'IDLE')
        self.assertTrue((Path(start['directory'])/'video.mp4').exists())
        self.assertIn('MP4 saved',controls.message)

    def test_recording_errors_clear_gui_without_flight_commands(self):
        commands, reports = queue.Queue(), queue.Queue()
        controls = CaptureControls(mp.get_context('spawn'),commands,reports,self.root,'handheld')
        controls.toggle()
        start = commands.get()
        reports.put(dict(event='record_error',directory=start['directory'],error='disk full'))
        controls.poll()
        self.assertIsNone(controls.active)
        self.assertEqual(controls.state,'ERROR')
        self.assertTrue(commands.empty())
        controls.toggle()
        self.assertEqual(commands.get()['action'],'start')

    def test_receiver_finally_closes_recording_and_delivers_video(self):
        # Exercise the actual UDP receiver with fake sockets and real H.264 decode.
        from tt_video_viewer import MAX_BYTES, receive_video
        ctx = mp.get_context('spawn')
        buffer, meta = ctx.RawArray('B',MAX_BYTES), ctx.Array('d',14)
        ready, stop = ctx.Event(), ctx.Event()
        commands, errors, reports = queue.Queue(), queue.Queue(), queue.Queue()
        directory = self.root/'receiver'
        commands.put(dict(action='start',directory=str(directory),kind='flight'))

        class FakeSocket:
            def __init__(self, payloads=()):
                self.payloads = iter(payloads)
            def setblocking(self, _):
                pass
            def recvfrom(self, _):
                try:
                    return next(self.payloads), ('192.168.50.24',11111)
                except StopIteration:
                    raise BlockingIOError
            def close(self):
                pass

        video, telemetry = FakeSocket(bytes(p) for p in self.packets), FakeSocket()
        calls = 0
        def available(*_):
            nonlocal calls
            calls += 1
            if calls > 1:
                stop.set()
                return [],[],[]
            return [video],[],[]

        with patch('tt_video_viewer.bind_udp',side_effect=[video,telemetry]), \
             patch('tt_video_viewer.select.select',side_effect=available):
            receive_video('192.168.50.21','192.168.50.24',7,buffer,meta,
                          ready,stop,errors,commands,reports)
        self.assertTrue(ready.is_set())
        self.assertTrue(errors.empty())
        self.assertGreater(meta[0],50)
        self.assertEqual((meta[2],meta[3]),(160,96))
        self.assertEqual([reports.get()['event'] for _ in range(2)],['started','closed'])
        self.assertTrue(json.loads((directory/'capture.json').read_text())['closed'])
        result = export_mp4(directory)
        with av.open(result['file']) as replay:
            self.assertEqual(len(list(replay.decode(video=0))),int(meta[0]))


if __name__ == '__main__':
    unittest.main()
