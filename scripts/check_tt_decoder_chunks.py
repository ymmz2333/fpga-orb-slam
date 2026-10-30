"""Offline check of H.264 parser chunk invariance on an existing recording.

Computer/PS diagnostic only. No network, drone commands or source-file changes.
Both paths use the same installed FFmpeg backend; this is NOT an independent
DJI decoder comparison and does not reproduce original UDP timing or loss.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import time

import av
import numpy as np


def fingerprint(frame):
    image = frame.to_ndarray(format='bgr24')
    return (frame.width, frame.height, hashlib.sha256(image.tobytes()).hexdigest())


def decode_chunks(data, size, *, seed=20260903):
    codec = av.CodecContext.create('h264', 'r')
    codec.thread_count = 1
    rng = random.Random(seed)
    offset = chunks = emitted_packets = 0
    results, decode_ms = [], []
    started = time.perf_counter()

    def consume(packet):
        nonlocal emitted_packets
        emitted_packets += 1
        begin = time.perf_counter()
        frames = codec.decode(packet)
        decode_ms.append((time.perf_counter() - begin) * 1000)
        results.extend(fingerprint(frame) for frame in frames)

    while offset < len(data):
        count = size if size else rng.randint(1, 2000)
        block = data[offset:offset + count]
        offset += len(block)
        chunks += 1
        for packet in codec.parse(block):
            consume(packet)
    before_eof = len(results)
    # Flush only because this is a FINISHED file. Never flush each UDP datagram.
    for packet in codec.parse(b''):
        consume(packet)
    results.extend(fingerprint(frame) for frame in codec.decode(None))
    elapsed = time.perf_counter() - started
    return results, dict(chunk_bytes=size or 'random 1..2000', chunks=chunks,
        parser_packets=emitted_packets, frames_before_eof_flush=before_eof,
        frames=len(results), elapsed_s=round(elapsed, 3),
        decode_call_p50_ms=round(float(np.percentile(decode_ms, 50)), 3),
        decode_call_p99_ms=round(float(np.percentile(decode_ms, 99)), 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    if not 0 < args.input.stat().st_size <= 32 * 1024 * 1024:
        parser.error('Use a finished H.264 recording of at most 32 MiB')
    data = args.input.read_bytes()
    with av.open(io.BytesIO(data), format='h264') as container:
        container.streams.video[0].codec_context.thread_count = 1
        baseline = [fingerprint(frame) for frame in container.decode(video=0)]
    if not baseline:
        raise RuntimeError('Recording contains no decodable frames')
    report = dict(input=str(args.input), input_sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data), pyav=av.__version__, ffmpeg_libraries=av.library_versions,
        baseline_frames=len(baseline), frame_sizes=sorted(set(x[:2] for x in baseline)),
        network_used=False, original_udp_boundaries_available=False,
        independent_dji_decoder_comparison=False, cases=[])
    for size in (1024, 1460, 4096, 0):
        decoded, case = decode_chunks(data, size)
        case['bgr_hash_sequence_matches'] = decoded == baseline
        report['cases'].append(case)
    print(json.dumps(report, indent=2))
    if not all(case['bgr_hash_sequence_matches'] for case in report['cases']):
        raise SystemExit('FAIL: chunk split changed decoded frame sequence')


if __name__ == '__main__':
    main()
