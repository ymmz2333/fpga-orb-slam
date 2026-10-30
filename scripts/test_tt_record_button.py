"""Offline Y-button recording tests; no aircraft commands or real XInput."""
import ctypes
import multiprocessing as mp
import queue
import tempfile
import unittest
from unittest.mock import Mock

from tt_controller_core import Pad, LB, RB
from tt_record_button import Y_BUTTON, RecordButton, NativePad, NativeState, drain_record_requests
from tt_video_capture import CaptureControls


class RecordButtonTests(unittest.TestCase):
    def test_press_and_hold_is_one_edge(self):
        button = RecordButton()
        self.assertFalse(button.tick(Pad(True)))
        self.assertTrue(button.tick(Pad(True,buttons=Y_BUTTON)))
        for _ in range(50):
            self.assertFalse(button.tick(Pad(True,buttons=Y_BUTTON)))

    def test_release_then_second_press(self):
        button = RecordButton()
        sequence = [0,Y_BUTTON,Y_BUTTON,0,Y_BUTTON,0]
        self.assertEqual([button.tick(Pad(True,buttons=b)) for b in sequence],
                         [False,True,False,False,True,False])

    def test_startup_held_needs_release(self):
        button = RecordButton()
        self.assertFalse(button.tick(Pad(True,buttons=Y_BUTTON)))
        self.assertFalse(button.tick(Pad(True,buttons=Y_BUTTON)))
        self.assertFalse(button.tick(Pad(True)))
        self.assertTrue(button.tick(Pad(True,buttons=Y_BUTTON)))

    def test_reconnect_held_needs_release(self):
        button = RecordButton()
        for pad in (Pad(True),Pad(False),Pad(True,buttons=Y_BUTTON),Pad(True,buttons=Y_BUTTON),Pad(True)):
            self.assertFalse(button.tick(pad))
        self.assertTrue(button.tick(Pad(True,buttons=Y_BUTTON)))

    def test_other_buttons_do_not_record(self):
        button = RecordButton()
        for buttons in (0,LB|RB,0,0x1000,0x2000,0x4000):
            self.assertFalse(button.tick(Pad(True,buttons=buttons)))

    def test_y_with_other_buttons_still_one_edge(self):
        button = RecordButton()
        button.tick(Pad(True))
        self.assertTrue(button.tick(Pad(True,buttons=Y_BUTTON|LB|RB)))
        self.assertFalse(button.tick(Pad(True,buttons=Y_BUTTON)))

    def test_native_structure_matches_xinput_layout(self):
        self.assertEqual(ctypes.sizeof(NativePad),12)
        self.assertEqual(ctypes.sizeof(NativeState),16)

    def test_dry_run_drains_without_recording(self):
        requests,capture = queue.Queue(),Mock()
        requests.put('toggle')
        self.assertEqual(drain_record_requests(requests,capture,enabled=False,video_available=True),0)
        capture.toggle.assert_not_called()
        self.assertTrue(requests.empty())

    def test_requests_reuse_start_stop_including_stale_stop(self):
        requests,commands,reports = queue.Queue(),queue.Queue(),queue.Queue()
        with tempfile.TemporaryDirectory() as root:
            capture = CaptureControls(mp.get_context('spawn'),commands,reports,root,'flight')
            requests.put('toggle')
            self.assertEqual(drain_record_requests(requests,capture,enabled=True,video_available=True),1)
            self.assertEqual(commands.get()['action'],'start')
            requests.put('toggle')
            drain_record_requests(requests,capture,enabled=True,video_available=False)
            self.assertEqual(commands.get()['action'],'stop')
            self.assertEqual(capture.state,'STOPPING')

    def test_no_video_does_not_start_capture(self):
        requests,commands,reports = queue.Queue(),queue.Queue(),queue.Queue()
        with tempfile.TemporaryDirectory() as root:
            capture = CaptureControls(mp.get_context('spawn'),commands,reports,root,'handheld')
            requests.put('toggle')
            drain_record_requests(requests,capture,enabled=True,video_available=False)
            self.assertTrue(commands.empty())
            self.assertIsNone(capture.active)


if __name__ == '__main__':
    unittest.main()
