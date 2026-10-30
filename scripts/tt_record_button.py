"""Computer-side Xbox Y recording input. No aircraft/network commands."""
import ctypes
from ctypes import wintypes
import queue

from tt_controller_core import Pad

Y_BUTTON = 0x8000


class NativePad(ctypes.Structure):
    _fields_ = [('buttons', wintypes.WORD), ('lt', wintypes.BYTE), ('rt', wintypes.BYTE),
                ('lx', ctypes.c_short), ('ly', ctypes.c_short),
                ('rx', ctypes.c_short), ('ry', ctypes.c_short)]


class NativeState(ctypes.Structure):
    _fields_ = [('packet', wintypes.DWORD), ('pad', NativePad)]


class WindowsRecordInput:
    """Read XInput for the video-only viewer; never interpret flight gestures."""
    def __init__(self,index=0):
        self.index = index
        self.dll = ctypes.WinDLL('xinput1_4.dll')
        self.dll.XInputGetState.argtypes = [wintypes.DWORD,ctypes.POINTER(NativeState)]
        self.dll.XInputGetState.restype = wintypes.DWORD

    def read(self):
        raw = NativeState()
        connected = self.dll.XInputGetState(self.index,ctypes.byref(raw)) == 0
        return Pad(connected=connected,buttons=raw.pad.buttons)


class RecordButton:
    """One edge per press. Startup/reconnection while held needs a release."""
    def __init__(self):
        self.connected = False
        self.pressed = True

    def tick(self,pad):
        if not pad.connected:
            self.connected,self.pressed = False,True
            return False
        pressed = bool(pad.buttons & Y_BUTTON)
        edge = self.connected and pressed and not self.pressed
        self.connected,self.pressed = True,pressed
        return edge


def drain_record_requests(requests,capture,*,enabled,video_available):
    """GUI owns capture state; flight worker only sends non-blocking requests."""
    count = 0
    while True:
        try:
            request = requests.get_nowait()
        except queue.Empty:
            return count
        if enabled and request == 'toggle':
            capture.toggle(video_available)
            count += 1
