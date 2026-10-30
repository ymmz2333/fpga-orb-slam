"""Media-only replay validation of PC and RK decoders using one raw recording."""
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import time

import av
import cv2

from tt_rk_bridge import RKBridge
from tt_decode_metrics import benchmark


def run(directory,output,rk_only=False,realtime=False,preview_encoder='auto'):
    directory,output = Path(directory),Path(output)
    output.mkdir(parents=True,exist_ok=False)
    raw = directory/'packets.h264'
    if not rk_only:
        for mode in ('software','d3d11va'):
            benchmark(raw,mode,output/(mode+'.json'))
    packets = mp.get_context('spawn').Queue(256)
    bridge = RKBridge(packets,output,preview_encoder=preview_encoder)
    try:
        if not bridge.ready.wait(12) or bridge.latest()[2].get('event') == 'error':
            raise RuntimeError('RK bridge did not become ready')
        count = 0
        started = time.perf_counter()
        with av.open(str(raw),format='h264') as source:
            for packet in source.demux(video=0):
                if packet.size:
                    if realtime:
                        time.sleep(max(0,started+count/30-time.perf_counter()))
                    count += 1
                    packets.put((count,time.perf_counter(),bytes(packet)),timeout=10)
        print('RK_INPUT_PACKETS '+str(count),flush=True)
    finally:
        bridge.close()
    image,_,stats = bridge.latest()
    if image is not None:
        cv2.imwrite(str(output/'rk_preview.png'),image)
    print(json.dumps(stats,indent=2),flush=True)
    if stats.get('event') != 'done' or stats.get('decoded') != count:
        raise RuntimeError('RK decoded-frame acceptance failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--output',required=True)
    parser.add_argument('--rk-only',action='store_true')
    parser.add_argument('--realtime',action='store_true',help='Pace replay at nominal 30 fps, not camera timestamps')
    parser.add_argument('--preview-encoder',choices=('auto','jpegenc','mppjpegenc','mppjpegenc-copy'),default='auto')
    args = parser.parse_args()
    run(args.directory,args.output,args.rk_only,args.realtime,args.preview_encoder)
