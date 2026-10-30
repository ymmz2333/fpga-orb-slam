"""Scoped Windows idle-sleep/display request for unattended PC experiment jobs."""
import ctypes
import os


class WindowsAwake:
    # Keep the display active as well: this laptop uses Modern Standby.
    FLAGS = 0x80000000 | 0x00000001 | 0x00000002

    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows execution request must run on the Windows coordinator')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
        self.api.argtypes = [ctypes.c_uint32]
        self.api.restype = ctypes.c_uint32
        self.active = False

    def acquire(self):
        previous = self.api(self.FLAGS)
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        self.active = True
        return dict(api='SetThreadExecutionState', flags=hex(self.FLAGS), previous_state=hex(previous),
                    system_required=True, display_required=True, active=True,
                    scope='calling thread only; no permanent sleep-policy changes')

    def release(self):
        if not self.active:
            return
        if not self.api(0x80000000):
            raise ctypes.WinError(ctypes.get_last_error())
        self.active = False
