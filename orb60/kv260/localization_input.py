"""KV260 PS ->7015 PS GRAY8 transport; actual camera and recording are explicit.

The peer acknowledgment proves image receipt/CRC, not ORB, pose or HDMI success.
"""
import hashlib
import re
import socket
import struct
import zlib
from orb60.linux.client import receive

SIZE=960*720


def header(frame,stamp,sequence,crc,calibration,mode):
    if (type(frame)!=int or not 0<=frame<=0xffffffffffffffff or type(stamp)!=int or not 0<stamp<=0xffffffffffffffff or
        type(sequence)!=int or not 0<=sequence<=0xffffffff or mode not in (0,1) or
        not 0<=crc<=0xffffffff or not re.fullmatch('[0-9a-f]{64}',calibration)):
        raise ValueError('Invalid explicit network camera identity/calibration/mode')
    out=bytearray(128);out[:8]=b'ORBGRAY1'
    struct.pack_into('<IIQQ8I',out,8,1,128,frame,stamp,SIZE,crc,960,720,mode,sequence,0,0)
    out[64:]=calibration.encode('ascii');struct.pack_into('<I',out,56,zlib.crc32(out));return bytes(out)


def validate_ack(data,frame,stamp,crc):
    if len(data)!=32 or data[:8]!=b'ORBGRAY2' or struct.unpack_from('<QQI',data,8)!=(frame,stamp,crc) or struct.unpack_from('<I',data,28)[0]!=zlib.crc32(data[:28]):
        raise ValueError('7015 camera acknowledgment identity/CRC mismatch')


class Sender:
    def __init__(self,host,port,calibration,mode,timeout=20):
        if mode not in (0,1):raise ValueError('Explicit real-camera0 or recorded-diagnostic1 mode required')
        self.calibration=hashlib.sha256(calibration).hexdigest();self.mode=mode;self.previous=-1;self.stamp=0;self.sequence=0;self.failed=False
        self.sock=socket.create_connection((host,port),timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)

    def send(self,gray,frame,stamp,sequence):
        if self.failed:raise RuntimeError('Failed network camera sender cannot be reused')
        if frame!=self.previous+1 or stamp<=self.stamp or len(gray)!=SIZE:
            raise ValueError('Monotonic sampled-frame identity and tight960x720 grayscale required')
        crc=zlib.crc32(gray);h=header(frame,stamp,sequence,crc,self.calibration,self.mode)
        try:
            self.sock.sendall(h);self.sock.sendall(gray);validate_ack(receive(self.sock,32),frame,stamp,crc)
        except BaseException:
            self.failed=True;self.close();raise
        self.previous,self.stamp,self.sequence=frame,stamp,sequence;return crc

    def finish_manual(self):
        if self.failed or self.mode!=0 or self.previous<0:raise ValueError('Explicit nonempty live manual stream required')
        h=bytearray(header(self.previous+1,self.stamp,self.sequence,0,self.calibration,0))
        h[:8]=b'ORBGRAY3';struct.pack_into('<I',h,32,0);struct.pack_into('<I',h,60,1)
        struct.pack_into('<I',h,56,0);struct.pack_into('<I',h,56,zlib.crc32(h))
        try:
            self.sock.sendall(h);ack=receive(self.sock,32)
            if (ack[:8]!=b'ORBEND02' or struct.unpack_from('<QQI',ack,8)!=(self.previous+1,self.stamp,0) or
                struct.unpack_from('<I',ack,28)[0]!=zlib.crc32(ack[:28])):raise ValueError('Manual network end acknowledgment mismatch')
        except BaseException:self.failed=True;self.close();raise

    def close(self):
        try:self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        self.sock.close()
