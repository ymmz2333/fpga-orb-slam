"""Fail-closed physical FPGA startup probe, using the existing strict wire decoder."""
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import socket
import time
import cv2
import csv


def endpoint(value):
    if value.startswith('['):
        host, port = value[1:].split(']:', 1)
    else:
        host, port = value.rsplit(':', 1)
    return host, int(port)


def verify(client_path, address, dataset):
    spec = importlib.util.spec_from_file_location('orb60_physical_wire', str(client_path))
    wire = importlib.util.module_from_spec(spec); spec.loader.exec_module(wire)
    stamp = next(s.strip() for s in (Path(dataset)/'timestamps.txt').read_text().splitlines() if s.strip())
    source = Path(dataset)/'mav0/cam0/data'/(stamp+'.png')
    image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (720, 960):
        raise RuntimeError('FPGA startup input is invalid: '+str(source))
    host, port = endpoint(address)
    identity = secrets.randbits(63) or 1
    client = wire.Client(host, port, timeout=5, allow_simulated=False)
    try:
        result, payload = client.extract(image.tobytes(), identity, int(stamp))
    finally:
        client.close()
    if result['simulated'] or result['engine_ns'] <= 0:
        raise RuntimeError('Physical PL execution counters are required')
    return dict(status='PASS', backend='physical_fpga', endpoint=address,
                frame_id=identity, timestamp_ns=int(stamp), count=result['count'],
                engine_ns=result['engine_ns'], roundtrip_ns=result['roundtrip_ns'],
                source=str(source), input_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                payload_sha256=hashlib.sha256(payload).hexdigest(), verified_at_ns=time.time_ns(),
                checks=['nonce/frame identity','timestamp','CRC','hardware flag','PL ABI/cycles'])


def verify_inputs(dataset):
    rows=list(csv.DictReader((Path(dataset)/'frames.csv').open()))
    for row in rows:
        path=Path(dataset)/row['image']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('Prepared input checksum mismatch: '+str(path))
    return dict(status='PASS',frames=len(rows),checks='Every generated PNG SHA256 matches source_frames.csv')
