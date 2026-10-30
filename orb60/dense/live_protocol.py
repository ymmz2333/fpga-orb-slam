"""Separate bounded dense-delta transport. ORBVIZ01 remains byte-for-byte unchanged."""
import json
import struct
import zlib

HEADER=struct.Struct('<8s4I')
MAX_META=65536;MAX_PAYLOAD=8*1024*1024


def encode(meta,payload=b''):
    text=json.dumps(meta,separators=(',',':'),allow_nan=False).encode()
    if len(text)>MAX_META or len(payload)>MAX_PAYLOAD:raise ValueError('Live dense packet exceeds bounds')
    body=text+payload
    return HEADER.pack(b'ORBDENS1',1,len(text),len(payload),zlib.crc32(body))+body


def receive(sock):
    def exact(n):
        buf=bytearray(n);at=0
        while at<n:
            count=sock.recv_into(memoryview(buf)[at:])
            if not count:raise ConnectionError('Dense stream closed')
            at+=count
        return bytes(buf)
    magic,version,n,p,crc=HEADER.unpack(exact(HEADER.size))
    if magic!=b'ORBDENS1' or version!=1 or not 2<=n<=MAX_META or p>MAX_PAYLOAD:
        raise ValueError('Invalid live dense packet header')
    body=exact(n+p)
    if zlib.crc32(body)!=crc:raise ValueError('Live dense CRC mismatch')
    return json.loads(body[:n],parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite metadata'))),body[n:]
