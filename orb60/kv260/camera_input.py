"""Native V4L2 capture on KV260 PS, with owned uncompressed color/luma pairs.

Camera timestamps and sequences are from V4L2, not synthesized video identities.
Sampling can skip old sensor frames; every gap is reported. No JPEG or ORB here.
"""
import ctypes as C
import json
import sys
from pathlib import Path
import cv2
import numpy as np
from orb60.demo_bridge.calibration import cropped, read


def fourcc(name):
    if name not in ('YUYV', 'UYVY'):
        raise ValueError('Explicit YUYV/UYVY required')
    return int.from_bytes(name.encode('ascii'), 'little')


def validate_profile(p):
    if (p['width'], p['height']) != (1280, 720) or p['fourcc'] not in (fourcc('YUYV'), fourcc('UYVY')):
        raise ValueError('Exact 1280x720 uncompressed format required')
    if p['stride'] < 2560 or p['sizeimage'] < p['stride'] * 719 + 2560 or not 2 <= p['buffers'] <= 4:
        raise ValueError('Invalid camera stride/capacity/buffer count')
    # Linux V4L2 defaults map sRGB -> BT.601, non-JPEG YUV -> limited range.
    # OpenCV's packed conversion implements that matrix/range. Other camera
    # colorimetry requires an explicit conversion, never a silent approximation.
    if p['colorspace'] != 8 or p['ycbcr_encoding'] not in (0, 1) or p['quantization'] not in (0, 2) or p['transfer_function'] not in (0, 1, 2):
        raise ValueError('Unsupported camera colorimetry; BT.601 limited YUV required')
    if min(p['interval_numerator'], p['interval_denominator']) <= 0:
        raise ValueError('Missing negotiated frame interval')


def validate_pair(packed, gray, p):
    if packed.dtype != np.uint8 or packed.shape != (720, 960, 2) or gray.dtype != np.uint8 or gray.shape != (720, 960):
        raise ValueError('Invalid camera color/luma shape or dtype')
    offset = int(p['fourcc'] == fourcc('UYVY'))
    if not np.array_equal(packed[:, :, offset], gray):
        raise ValueError('Color and PL luminance do not describe the same frame')


def to_bgr(packed, p):
    validate_profile(p)
    if packed.dtype != np.uint8 or packed.shape != (720, 960, 2):
        raise ValueError('Expected cropped packed 960x720 color')
    code = cv2.COLOR_YUV2BGR_YUY2 if p['fourcc'] == fourcc('YUYV') else cv2.COLOR_YUV2BGR_UYVY
    return cv2.cvtColor(packed, code)


def validate_calibration(source, working):
    expected = cropped(read(Path(source).read_bytes()))
    actual = read(Path(working).read_bytes())
    if actual != expected:
        raise ValueError('Camera crop/calibration mismatch')
    return actual


class Camera:
    def __init__(self, library, device='/dev/video0', fps=60, encoding='YUYV'):
        if not sys.platform.startswith('linux'):
            raise ValueError('Actual Linux V4L2 camera required')
        self.lib = C.CDLL(str(Path(library).resolve()))
        self.lib.orb_camera_open.argtypes = [C.c_char_p, C.c_uint32, C.c_uint, C.c_void_p, C.c_size_t]
        self.lib.orb_camera_open.restype = C.c_void_p
        self.lib.orb_camera_profile.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        self.lib.orb_camera_profile.restype = C.c_int
        self.lib.orb_camera_next.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_uint]
        self.lib.orb_camera_next.restype = C.c_int
        self.lib.orb_camera_close.argtypes = [C.c_void_p]
        self.lib.orb_camera_close.restype = C.c_int
        error = C.create_string_buffer(2048)
        self.handle = self.lib.orb_camera_open(str(device).encode(), fourcc(encoding), fps, error, len(error))
        self.failed = False
        if not self.handle:
            raise RuntimeError(error.value.decode())
        try:
            p = self.profile()
            validate_profile(p)
            if p['interval_denominator'] != fps * p['interval_numerator']:
                raise ValueError('Camera did not accept requested frame rate')
        except BaseException:
            self.close()
            raise

    def profile(self):
        if not self.handle:
            raise RuntimeError('Camera is closed')
        out = C.create_string_buffer(2048)
        if self.lib.orb_camera_profile(self.handle, out, len(out)):
            raise RuntimeError('Camera profile overflow')
        return json.loads(out.value)

    def next(self, timeout_ms=3000):
        if not self.handle or self.failed:
            raise RuntimeError('Failed/closed camera cannot be reused')
        packed = np.empty((720, 960, 2), np.uint8)
        gray = np.empty((720, 960), np.uint8)
        out = C.create_string_buffer(2048)
        if self.lib.orb_camera_next(self.handle, packed.ctypes.data, packed.nbytes, gray.ctypes.data, gray.nbytes, out, len(out), timeout_ms):
            self.failed = True
            raise RuntimeError(out.value.decode())
        return packed, gray, json.loads(out.value)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if self.lib.orb_camera_close(handle):
                raise RuntimeError('Camera STREAMOFF failed')
