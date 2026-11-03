"""Offline packed YUYV/UYVY replay preparation; no compressed decode at runtime."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import time
import zlib
import cv2
import numpy as np
from .direct_gray import digest,rows,validate as validate_source

HEADER=struct.Struct('<8sQQII')
FORMATS={'YUYV':(b'ORBYUYV1',cv2.COLOR_YUV2BGR_YUY2,0),'UYVY':(b'ORBUYVY1',cv2.COLOR_YUV2BGR_UYVY,1)}
FRAME_BYTES=32+960*720*2


def unpack(packed,kind,lut):
    if kind not in FORMATS or packed.dtype!=np.uint8 or packed.shape!=(720,960,2) or not packed.flags.c_contiguous:
        raise ValueError('Explicit original-size packed YUYV/UYVY required')
    if lut.shape!=(256,) or lut.dtype!=np.uint8:raise ValueError('Explicit256-byte luminance LUT required')
    _,code,y=FORMATS[kind]
    return cv2.cvtColor(packed,code),lut[packed[:,:,y]]


def prepare(video,source_inputs,output,kind='YUYV'):
    import av
    video,source_inputs,output=map(Path,(video,source_inputs,output))
    if kind not in FORMATS:raise ValueError('Explicit packed input format required')
    source=validate_source(source_inputs/'SOURCE.json',video,source_inputs/'identities.csv',source_inputs/'color_identities.csv',source_inputs/'reference_features.csv')
    if shutil.disk_usage(output.parent).free<FRAME_BYTES*source['frames']+512*1024**2:raise ValueError('Packed replay needs source bytes plus512MiB free margin')
    output.mkdir(parents=True,exist_ok=False);ids=rows(source_inputs/'identities.csv');started=time.monotonic()
    state=dict(status='RUNNING',scope='Offline uncompressed camera-format replay from saved video; conversion excluded from subsequent native processing, not live camera FPS',
               format=kind,width=960,height=720,frame_bytes=FRAME_BYTES,frames=0,gray_mismatches=[],source_proof_sha256=digest(source_inputs/'SOURCE.json'),video_sha256=source['video_sha256'],pyav=av.__version__,opencv=cv2.__version__)
    whole=hashlib.sha256();lut=None;source_range=None
    try:
        with av.open(str(video)) as c,(output/'frames.p422').open('wb') as raw,(output/'color_identities.csv').open('w',newline='') as colors:
            stream=c.streams.video[0];stream.codec_context.thread_type='SLICE';stream.codec_context.thread_count=5
            writer=csv.writer(colors,lineterminator='\n');writer.writerow(['source_frame_id','timestamp_ns','bgr_crc'])
            for i,frame in enumerate(c.decode(stream)):
                if i>=len(ids):raise ValueError('Extra offline source frame')
                if lut is None:
                    fixture=av.VideoFrame(256,2,'yuyv422');a=np.empty((2,256,2),np.uint8);a[:,:,0]=np.arange(256,dtype=np.uint8);a[:,:,1]=128
                    fixture.planes[0].update(a.tobytes());fixture.color_range=frame.color_range
                    lut=np.ascontiguousarray(fixture.to_ndarray(format='gray')[0]);source_range=int(frame.color_range)
                    (output/'gray_lut.bin').write_bytes(lut.tobytes())
                if int(frame.color_range)!=source_range:raise ValueError('Dynamic source color range is not supported')
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
                p=frame.to_ndarray(format='yuyv422')
                if kind=='UYVY':p=np.ascontiguousarray(p[:,:,::-1])
                bgr,gray=unpack(p,kind,lut);original=frame.to_ndarray(format='gray');row=ids[i]
                if (i,stamp)!=(int(row['source_frame_id']),int(row['timestamp_ns'])):raise ValueError('Original packed frame association mismatch')
                gc=zlib.crc32(memoryview(gray))
                if not np.array_equal(gray,original) or gc!=int(row['gray_crc']):state['gray_mismatches'].append(i)
                header=HEADER.pack(FORMATS[kind][0],i,stamp,zlib.crc32(memoryview(p)),gc)
                raw.write(header);raw.write(memoryview(p));whole.update(header);whole.update(memoryview(p))
                writer.writerow([i,stamp,zlib.crc32(memoryview(bgr))]);state['frames']=i+1
        if state['frames']!=len(ids) or state['gray_mismatches']:raise ValueError('Packed luminance did not preserve original direct-gray pixels')
        for name in ('identities.csv','reference_features.csv'):shutil.copyfile(source_inputs/name,output/name)
        state.update(status='PACKED_YUV_SOURCE_PREPARED',color_range=source_range,source_sha256=digest(__file__),data_sha256=whole.hexdigest(),data_bytes=(output/'frames.p422').stat().st_size,
                     files_sha256={n:digest(output/n) for n in ('gray_lut.bin','identities.csv','reference_features.csv','color_identities.csv')})
        if state['data_bytes']!=FRAME_BYTES*state['frames']:raise ValueError('Packed source size mismatch')
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        state['offline_conversion_seconds']=time.monotonic()-started
        (output/'SOURCE.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


def validate(proof,raw,identities,color_identities,reference,lut):
    p=json.loads(Path(proof).read_text())
    if p.get('status')!='PACKED_YUV_SOURCE_PREPARED' or p.get('source_sha256')!=digest(__file__) or p.get('format') not in FORMATS or p.get('frames')!=2297 or p.get('gray_mismatches'):
        raise ValueError('Complete original-gray packed source proof required')
    raw=Path(raw)
    if raw.stat().st_size!=p['data_bytes'] or p['data_bytes']!=FRAME_BYTES*p['frames'] or digest(raw)!=p['data_sha256']:
        raise ValueError('Packed raw input changed')
    for n,f in [('identities.csv',identities),('color_identities.csv',color_identities),('reference_features.csv',reference),('gray_lut.bin',lut)]:
        if digest(f)!=p['files_sha256'][n]:raise ValueError('Packed source manifest/LUT mismatch: '+n)
    if Path(lut).stat().st_size!=256:raise ValueError('Packed gray LUT must be256bytes')
    return p


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('video','source_inputs','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    p.add_argument('--kind',choices=tuple(FORMATS),default='YUYV');prepare(**vars(p.parse_args()))
