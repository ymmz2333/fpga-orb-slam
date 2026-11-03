"""Camera-byte emulation only: seal and send original uncompressed packets."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import socket
import struct
import time
import zlib

HEADER=struct.Struct('<8sQQII');PRELUDE=struct.Struct('<8s32sQ');PAYLOAD_BYTES=960*720*2
MAGIC={'YUYV':b'ORBYUYV1','UYVY':b'ORBUYVY1'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def read_rows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))


def validate_contract(proof,source,headers,identities,colors,reference,lut):
    p,s=load(proof),load(source)
    if p.get('status')!='PACKED_SENSOR_BYTES_SEALED' or p.get('sealer_sha256')!=digest(__file__):raise ValueError('Explicit sealed sensor-byte source required')
    if s.get('status')!='PACKED_YUV_SOURCE_PREPARED' or s.get('source_sha256')!=digest(Path(__file__).with_name('packed_yuv.py')) or s.get('frames')!=2297 or s.get('gray_mismatches') or s.get('format') not in MAGIC:raise ValueError('Original packed source proof mismatch')
    if p['source_proof_sha256']!=digest(source) or p['data_sha256']!=s['data_sha256'] or p['frames']!=s['frames'] or p['format']!=s['format'] or p['headers_sha256']!=digest(headers):raise ValueError('Sealed sensor source/header identity mismatch')
    for n,f in [('identities.csv',identities),('color_identities.csv',colors),('reference_features.csv',reference),('gray_lut.bin',lut)]:
        if digest(f)!=s['files_sha256'][n]:raise ValueError('Sensor source manifest/LUT mismatch: '+n)
    data=Path(headers).read_bytes();ids=read_rows(identities)
    if len(data)!=s['frames']*32 or len(ids)!=s['frames']:raise ValueError('Incomplete sensor header/identity scope')
    for i,row in enumerate(ids):
        magic,index,stamp,_,gray=HEADER.unpack_from(data,i*32)
        if magic!=MAGIC[s['format']] or (index,stamp,gray)!=(int(row['source_frame_id']),int(row['timestamp_ns']),int(row['gray_crc'])):raise ValueError('Sensor header differs from original frame identity')
    return p,s


def seal(raw,source,identities,output):
    raw,output=Path(raw),Path(output);s=load(source);ids=read_rows(identities)
    if s.get('status')!='PACKED_YUV_SOURCE_PREPARED' or s['format'] not in MAGIC or raw.stat().st_size!=s['data_bytes'] or digest(identities)!=s['files_sha256']['identities.csv']:raise ValueError('Original raw source and identities required')
    output.mkdir(parents=True,exist_ok=False);whole=hashlib.sha256();headers=bytearray()
    with raw.open('rb') as f:
        for i,row in enumerate(ids):
            header=f.read(32);body=f.read(PAYLOAD_BYTES)
            if len(header)!=32 or len(body)!=PAYLOAD_BYTES:raise ValueError('Incomplete raw source')
            magic,index,stamp,crc,gray=HEADER.unpack(header)
            if magic!=MAGIC[s['format']] or (index,stamp,gray)!=(i,int(row['timestamp_ns']),int(row['gray_crc'])) or zlib.crc32(body)!=crc:raise ValueError('Original raw packet identity/CRC mismatch')
            headers.extend(header);whole.update(header);whole.update(body)
        if f.read(1) or len(ids)!=s['frames'] or whole.hexdigest()!=s['data_sha256']:raise ValueError('Raw master SHA256/coverage mismatch')
    (output/'headers.bin').write_bytes(headers)
    p=dict(status='PACKED_SENSOR_BYTES_SEALED',scope='Temporary PC camera-byte source only; no ORB, SLAM, depth, fusion or GPU compute on PC. Not final standalone/direct-cable acceptance',
           format=s['format'],frames=s['frames'],data_bytes=s['data_bytes'],data_sha256=whole.hexdigest(),source_proof_sha256=digest(source),headers_sha256=digest(output/'headers.bin'),sealer_sha256=digest(__file__))
    (output/'SOURCE_STREAM.json').write_text(json.dumps(p,indent=2)+'\n');print(json.dumps(p),flush=True)


def endpoint(value):
    if value.startswith('['):
        end=value.find(']')
        if end<1 or value[end+1:end+2]!=':':raise ValueError('Expected [IPv6%interface]:port')
        host,port=value[1:end],value[end+2:]
    else:
        if value.count(':')!=1:raise ValueError('Expected source-receiver address:port')
        host,port=value.rsplit(':',1)
    if not host or not port.isdecimal() or not 1<=int(port)<=65535:raise ValueError('Invalid receiver endpoint')
    return host,int(port)


def send(raw,proof,headers,address,report,frames=0):
    p=load(proof);raw=Path(raw);expected=Path(headers).read_bytes();report=Path(report)
    if report.exists() or p.get('status')!='PACKED_SENSOR_BYTES_SEALED' or p['sealer_sha256']!=digest(__file__) or p['headers_sha256']!=digest(headers) or len(expected)!=p['frames']*32 or raw.stat().st_size!=p['data_bytes'] or digest(raw)!=p['data_sha256']:
        raise ValueError('Explicit fresh sender report and unchanged raw source/proof required')
    if type(frames)!=int or frames<0 or frames>p['frames']:raise ValueError('Invalid sender prefix')
    count=frames or p['frames'];began=time.monotonic();sock=None;state=dict(status='CONNECTING',source_scope=p['scope'],requested_frames=count,sent_frames=0,master_sha256=p['data_sha256'],prefix=bool(frames))
    try:
        address=endpoint(address);deadline=time.monotonic()+240
        while sock is None:
            try:sock=socket.create_connection(address,timeout=1)
            except OSError:
                if time.monotonic()>deadline:raise TimeoutError('Native sensor receiver did not open within240seconds')
                time.sleep(.2)
        sock.settimeout(30);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        state['connected_monotonic_ns']=time.monotonic_ns();started=time.monotonic()
        sock.sendall(PRELUDE.pack(b'ORBSTRM1',bytes.fromhex(p['data_sha256']),p['frames']))
        with raw.open('rb') as f:
            for i in range(count):
                block=f.read(32+PAYLOAD_BYTES)
                if len(block)!=32+PAYLOAD_BYTES or block[:32]!=expected[i*32:(i+1)*32]:raise ValueError('Raw source packet changed during send')
                sock.sendall(block);state['sent_frames']=i+1
        sock.shutdown(socket.SHUT_WR)
        state.update(status='CAMERA_EMULATION_BYTES_SENT',send_seconds=time.monotonic()-started,sent_bytes=count*(32+PAYLOAD_BYTES),scope='Sender throughput only; use KV260 native+DPU+Mali result for system FPS')
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if sock:sock.close()
        state['total_seconds_including_connect']=time.monotonic()-began;report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('seal')
    for k in ('raw','source','identities','output'):a.add_argument('--'+k,type=Path,required=True)
    a=sub.add_parser('send')
    for k in ('raw','proof','headers','report'):a.add_argument('--'+k,type=Path,required=True)
    a.add_argument('--address',required=True);a.add_argument('--frames',type=int,default=0)
    v=vars(p.parse_args());action=v.pop('action');globals()[action](**v)
