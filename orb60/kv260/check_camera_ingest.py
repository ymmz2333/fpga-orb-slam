"""Finite actual KV260 USB camera -> 7015 PL -> KV260 receipt test.

No saved image/feature/pose fallback; this is an input/frontend component gate,
not complete SLAM, DPU, dense fusion or motion-based localization acceptance.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shlex
import time
import zlib
import cv2
import numpy as np
from .camera_input import Camera, validate_calibration, validate_pair, to_bgr
from .network_frontend import NetworkFrontend
from .two_board_session import Board


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(a):
    cv2.setNumThreads(1)
    if not 2 <= a.frames <= 3600:
        raise ValueError('Finite camera gate requires 2..3600 frames')
    validate_calibration(a.source_camera, a.camera)
    a.output.mkdir(parents=True, exist_ok=False)
    result = dict(status='RUNNING', input='actual_KV260_USB_uncompressed_camera',
                  scope='Camera / physical ORB / board-to-board transport component only; no SLAM, DPU or GPU claim',
                  camera_sha256=sha(a.camera), source_camera_sha256=sha(a.source_camera),
                  library_sha256=sha(a.library), boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  frames_requested=a.frames, physical_orb_used=bool(a.endpoint), resized=False,
                  source_geometry=[1280,720], working_geometry=[960,720], crop=[160,0,960,720])
    board = front = camera = None
    samples = []
    try:
        if bool(a.endpoint) != bool(a.connection):
            raise ValueError('Owned 7015 SSH frontend and explicit endpoint must be used together')
        if a.endpoint:
            config = json.loads(a.connection.read_text())
            from .network_frontend import endpoint
            if endpoint(a.endpoint)[0] != config['host']:
                raise ValueError('ORB endpoint and owned SSH peer differ')
            board = Board(a.root, config, a.output)
            release = shlex.quote(config['frontend_release'])
            board.run('set -eu; test ! -e /run/orb-demo.lock; '
                      'test "$(cat /sys/class/uio/uio0/version)" = wc1; '
                      '(cd '+release+' && sha256sum -c SHA256SUMS); '
                      'test "$(sha256sum '+shlex.quote(config['frontend_release']+'/bin/orb60-server')+
                      ' | cut -d " " -f 1)" = '+shlex.quote(config['frontend_sha256'])+'; '
                      'cat /proc/sys/kernel/random/boot_id', 'camera_frontend_preflight')
            board.start_frontend()
            front = NetworkFrontend(a.endpoint)
        camera = Camera(a.library, a.device, a.fps, a.encoding)
        profile = camera.profile()
        result['negotiated_profile'] = profile
        started = time.monotonic_ns()
        previous_seq = previous_ts = None
        fields = ['source_frame_id','capture_sequence','timestamp_ns','sequence_gaps','gray_crc','packed_crc',
                  'record_crc','count','engine_ns','roundtrip_ms','capture_age_ms','color_ms','step_ms']
        with (a.output/'frames.csv').open('w',newline='') as f:
            journal = csv.DictWriter(f,fieldnames=fields);journal.writeheader()
            for index in range(a.frames):
                began = time.monotonic_ns()
                packed, gray, meta = camera.next()
                validate_pair(packed, gray, profile)
                seq,stamp = meta['capture_sequence'],meta['timestamp_ns']
                delta = (seq-previous_seq) & 0xffffffff if previous_seq is not None else 1
                if (previous_ts is not None and stamp <= previous_ts) or not 0 < delta < 0x80000000:
                    raise ValueError('Camera identity duplicated/reversed')
                previous_seq,previous_ts = seq,stamp
                gray_crc,packed_crc = zlib.crc32(gray),zlib.crc32(packed)
                payload = b'';orb = dict(count=0,engine_ns=0,roundtrip_ns=0,records=b'')
                if front:
                    payload,orb = front.run(gray,index,stamp)
                before_color = time.monotonic_ns()
                bgr = to_bgr(packed,profile)
                color_ms = (time.monotonic_ns()-before_color)*1e-6
                row = dict(source_frame_id=index,capture_sequence=seq,timestamp_ns=stamp,
                           sequence_gaps=meta['sequence_gaps'],gray_crc=gray_crc,packed_crc=packed_crc,
                           record_crc=zlib.crc32(orb['records']),count=orb['count'],engine_ns=orb['engine_ns'],
                           roundtrip_ms=orb['roundtrip_ns']*1e-6,
                           capture_age_ms=(meta['dequeued_ns']-stamp)*1e-6,color_ms=color_ms,
                           step_ms=(time.monotonic_ns()-began)*1e-6)
                journal.writerow(row);f.flush();samples.append(row)
                if index in (0,a.frames//2,a.frames-1):
                    stem=a.output/('sample_%04d'%index)
                    if not cv2.imwrite(str(stem.with_suffix('.png')),bgr):
                        raise RuntimeError('Color preview write failed')
                    stem.with_suffix('.gray8').write_bytes(gray.tobytes())
                    stem.with_suffix('.'+a.encoding.lower()).write_bytes(packed.tobytes())
                    if front:stem.with_suffix('.payload').write_bytes(payload)
                if (index+1)%30==0:
                    print(json.dumps(dict(frames=index+1,physical_orb=bool(front),sequence_gaps=meta['sequence_gaps'])),flush=True)
        elapsed = (time.monotonic_ns()-started)*1e-9
        result.update(status='ACTUAL_USB_CAMERA_PHYSICAL_ORB_COMPONENT_PASS' if front else 'ACTUAL_USB_CAMERA_CAPTURE_COMPONENT_PASS',
                      frames=len(samples),seconds=elapsed,processed_fps=len(samples)/elapsed,
                      capture_timestamp_fps=(len(samples)-1)/((samples[-1]['timestamp_ns']-samples[0]['timestamp_ns'])*1e-9),
                      camera_profile=camera.profile(),cpu_orb_calls=0,
                      color_luma_pair_mismatches=0,all_pl_payloads_abi_validated=bool(front))
        for field in ('roundtrip_ms','capture_age_ms','color_ms','step_ms'):
            result[field]={name:float(np.percentile([r[field] for r in samples],percent))
                           for name,percent in (('p50',50),('p95',95),('p99',99))}
        result['feature_count_range']=[min(r['count'] for r in samples),max(r['count'] for r in samples)]
    except BaseException as error:
        result.update(status='FAILED',error=repr(error),frames=len(samples))
        raise
    finally:
        cleanup_errors=[]
        for obj,method in ((camera,'close'),(front,'close'),(board,'stop_frontend')):
            if obj:
                try:getattr(obj,method)()
                except BaseException as error:cleanup_errors.append(repr(error))
        if cleanup_errors:
            result.update(status='FAILED',cleanup_errors=cleanup_errors)
        result['source_hashes']={p.name:sha(p) for p in (
            Path(__file__),Path(__file__).with_name('camera_input.py'),Path(__file__).parent/'camera/v4l2_capture.c')}
        (a.output/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
        if cleanup_errors:raise RuntimeError('Camera/frontend cleanup failed: '+str(cleanup_errors))
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('library','camera','source-camera','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--device',default='/dev/video0')
    p.add_argument('--fps',type=int,default=60)
    p.add_argument('--encoding',choices=('YUYV','UYVY'),default='YUYV')
    p.add_argument('--frames',type=int,default=180)
    p.add_argument('--root',type=Path)
    p.add_argument('--connection',type=Path)
    p.add_argument('--endpoint')
    run(p.parse_args())
