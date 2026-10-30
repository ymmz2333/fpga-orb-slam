"""Bounded little-endian framing shared with bridge_wire.hpp; never CPU ORB."""
import enum
import socket
import struct
import zlib
from dataclasses import dataclass

MAGIC = b'ORB2DEMO'
VERSION = 1
HEADER = struct.Struct('<8sIIQQQIIIIII')
MAX_BODY = 32 * 1024 * 1024
IMAGE_BYTES = 960 * 720
PROFILE = 'ORB60-A32-4PPC-150MHZ-V1'


class Kind(enum.IntEnum):
    HELLO = 1
    FRAME = 2
    ACK = 3
    END = 4
    CONTROL = 5
    STATUS = 6
    MAP_BEGIN = 7
    MAP_FILE = 8
    MAP_COMMIT = 9
    ERROR = 10
    COLOR = 11


@dataclass(frozen=True)
class Packet:
    kind: int
    session: int = 0
    frame: int = 0
    stamp: int = 0
    count: int = 0
    aux: int = 0
    flags: int = 0
    body: bytes = b''

    def encode(self):
        if len(self.body) > MAX_BODY:
            raise ValueError('Bridge payload exceeds bound')
        return HEADER.pack(MAGIC, VERSION, self.kind, self.session, self.frame,
                           self.stamp, len(self.body), self.count, self.aux,
                           zlib.crc32(self.body), self.flags, 0) + self.body

    @classmethod
    def decode(cls, data):
        if len(data) < HEADER.size:
            raise ValueError('Truncated bridge header')
        m, v, k, s, f, t, n, count, aux, crc, flags, reserved = HEADER.unpack_from(data)
        if m != MAGIC or v != VERSION or reserved or k not in Kind._value2member_map_:
            raise ValueError('Unsupported bridge header')
        if n > MAX_BODY or len(data) != HEADER.size + n:
            raise ValueError('Invalid bridge body length')
        body = data[HEADER.size:]
        if zlib.crc32(body) != crc:
            raise ValueError('Bridge CRC mismatch')
        return cls(k, s, f, t, count, aux, flags, body)


def receive_exact(sock, size):
    data = bytearray(size)
    at = 0
    while at < size:
        n = sock.recv_into(memoryview(data)[at:])
        if not n:
            raise ConnectionError('Bridge disconnected')
        at += n
    return bytes(data)


def receive(sock):
    header = receive_exact(sock, HEADER.size)
    m, v, k, _, _, _, n, _, _, _, _, reserved = HEADER.unpack(header)
    if m != MAGIC or v != VERSION or reserved or k not in Kind._value2member_map_ or n > MAX_BODY:
        raise ValueError('Invalid bridge header before allocation')
    return Packet.decode(header + receive_exact(sock, n))


def connect(host, port, timeout=10):
    sock = socket.create_connection((host, port), timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(timeout)
    return sock


def validate_frame(packet):
    if packet.kind != Kind.FRAME or not packet.session or not packet.stamp or packet.flags & ~1:
        raise ValueError('Physical frame identity/provenance required')
    if packet.count > 1000 or len(packet.body) != IMAGE_BYTES + 128 + packet.count * 64 + 1024:
        raise ValueError('Frame geometry/result length mismatch')
    if zlib.crc32(packet.body[:IMAGE_BYTES]) != packet.aux:
        raise ValueError('Working gray CRC mismatch')
    return packet.body[:IMAGE_BYTES], packet.body[IMAGE_BYTES:]


def command(host, port, action):
    with connect(host, port) as sock:
        sock.sendall(Packet(Kind.CONTROL, body=action.encode('ascii')).encode())
        packet = receive(sock)
    if packet.kind == Kind.ERROR:
        raise RuntimeError(packet.body.decode('utf-8', 'replace'))
    if packet.kind != Kind.STATUS:
        raise ValueError('Unexpected control response')
    import json
    return json.loads(packet.body)
