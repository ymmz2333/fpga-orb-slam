"""Explicit lossless camera-emulator transport; native pixels remain unchanged."""
import argparse,hashlib,json,os,socket,struct,time,zlib
from pathlib import Path
from .packed_stream import endpoint
from .sensor_compression import Codec,RAW_BYTES,FRAME_COUNT,BLOCK,sha

PRELUDE=struct.Struct('<8s32sI')


def validate(proof,stream_proof,headers):
    p=json.loads(Path(proof).read_text());s=json.loads(Path(stream_proof).read_text());hd=Path(headers).read_bytes()
    if p.get('status')!='LOSSLESS_RAW_SENSOR_ARCHIVE_SEALED' or p.get('codec')!='lz4' or p.get('frames')!=FRAME_COUNT or p.get('raw_bytes_per_frame')!=RAW_BYTES:raise ValueError('Explicit complete lossless source required')
    if s.get('status')!='PACKED_SENSOR_BYTES_SEALED' or p['raw_source_sha256']!=s['data_sha256'] or p['stream_proof_sha256']!=sha(stream_proof) or p['headers_sha256']!=sha(headers) or len(hd)!=FRAME_COUNT*32 or len(p['packets'])!=FRAME_COUNT:raise ValueError('Lossless/original sealed source differs')
    for i,row in enumerate(p['packets']):
        if row['frame']!=i or not 0<row['compressed_bytes']<RAW_BYTES*2 or row['raw_header_hex']!=hd[i*32:(i+1)*32].hex():raise ValueError('Lossless packet index/header differs')
    return p,hd


def verify_receipt(proof,stream_proof,headers,receipt):
    p,_=validate(proof,stream_proof,headers);r=json.loads(Path(receipt).read_text())
    if r.get('status')!='LOSSLESS_SENSOR_BRIDGE_DRAINED' or r.get('codec')!='lz4' or r.get('frames')!=FRAME_COUNT or not r.get('all_declared_packets_forwarded') or r.get('raw_source_sha256_declared')!=p['raw_source_sha256'] or r.get('archive_sha256')!=p['archive_sha256'] or r.get('proof_sha256')!=sha(proof):raise ValueError('Full explicit lossless source bridge receipt required')
    return r


def prepare(raw,stream_proof,headers,output):
    raw,stream_proof,headers,output=map(Path,(raw,stream_proof,headers,output));s=json.loads(stream_proof.read_text());hd=headers.read_bytes()
    if s['status']!='PACKED_SENSOR_BYTES_SEALED' or s['frames']!=FRAME_COUNT or raw.stat().st_size!=FRAME_COUNT*RAW_BYTES or sha(raw)!=s['data_sha256'] or sha(headers)!=s['headers_sha256']:raise ValueError('Full immutable raw source required')
    output.mkdir(parents=True,exist_ok=False);archive=output/'frames.lz4blocks';codec=Codec('lz4');whole=hashlib.sha256();began=time.monotonic()
    p=dict(status='RUNNING',scope='Offline camera-byte preparation only; no vision computation. LZ4 is transport encoding, not a compressed camera format. Native input remains original YUYV/UYVY.',codec='lz4',codec_version=codec.version,frames=FRAME_COUNT,raw_bytes_per_frame=RAW_BYTES,raw_source_sha256=s['data_sha256'],stream_proof_sha256=sha(stream_proof),headers_sha256=sha(headers),preparer_sha256=sha(__file__),packets=[])
    try:
        with raw.open('rb') as f,archive.open('wb') as out:
            for i in range(FRAME_COUNT):
                data=f.read(RAW_BYTES)
                if len(data)!=RAW_BYTES or data[:32]!=hd[i*32:(i+1)*32] or zlib.crc32(data[32:])!=struct.unpack_from('<I',data,24)[0]:raise ValueError('Original raw packet identity differs')
                compressed=codec.encode(data);decoded=codec.decode(compressed)
                if decoded!=data:raise ValueError('Offline codec changed original bytes')
                whole.update(decoded);out.write(BLOCK.pack(i,RAW_BYTES,len(compressed)));out.write(compressed)
                p['packets'].append(dict(frame=i,compressed_bytes=len(compressed),compressed_crc32=zlib.crc32(compressed),raw_header_hex=data[:32].hex()))
                if (i+1)%300==0:print('LOSSLESS_SOURCE_PREPARED',i+1,flush=True)
            if f.read(1) or whole.hexdigest()!=s['data_sha256']:raise ValueError('Decoded full raw master differs')
        p.update(status='LOSSLESS_RAW_SENSOR_ARCHIVE_SEALED',archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,decoded_source_sha256=whole.hexdigest(),prepare_seconds=time.monotonic()-began)
    except BaseException as e:p.update(status='FAILED',error=repr(e));raise
    finally:(output/'SOURCE_LOSSLESS.json').write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps({k:p[k] for k in ('status','frames','archive_bytes','archive_sha256','prepare_seconds')}),flush=True)


def exact(sock,n):
    data=bytearray()
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise ValueError('Truncated lossless sensor stream')
        data.extend(part)
    return bytes(data)


def connect(address,seconds):
    deadline=time.monotonic()+seconds
    while True:
        try:
            s=socket.create_connection(endpoint(address),timeout=1);s.settimeout(30);return s
        except OSError:
            if time.monotonic()>deadline:raise TimeoutError('Lossless camera-emulator receiver unavailable')
            time.sleep(.2)


def send(archive,proof,stream_proof,headers,address,report):
    p,_=validate(proof,stream_proof,headers);archive,report=Path(archive),Path(report)
    if report.exists() or archive.stat().st_size!=p['archive_bytes'] or sha(archive)!=p['archive_sha256']:raise ValueError('Unchanged compressed master and fresh sender report required')
    state=dict(status='CONNECTING',codec='lz4',frames=0,archive_sha256=p['archive_sha256'],scope='PC sends sealed camera bytes only; no ORB/SLAM/depth/fusion/GPU compute');sock=None
    try:
        sock=connect(address,240);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sock.sendall(PRELUDE.pack(b'ORBCLZ41',bytes.fromhex(p['archive_sha256']),FRAME_COUNT))
        # Native SLAM loads its vocabulary before opening the raw source.
        # Do not stream payload into the bridge until that consumer is ready.
        sock.settimeout(180)
        if exact(sock,8)!=b'ORBRDY01':raise ValueError('Lossless native consumer readiness differs')
        sock.settimeout(30);began=time.monotonic()
        with archive.open('rb') as f:
            for i,row in enumerate(p['packets']):
                head=f.read(BLOCK.size);data=f.read(row['compressed_bytes'])
                if head!=BLOCK.pack(i,RAW_BYTES,len(data)) or len(data)!=row['compressed_bytes'] or zlib.crc32(data)!=row['compressed_crc32']:raise ValueError('Sealed compressed packet changed')
                sock.sendall(head+data);state['frames']=i+1
            if f.read(1):raise ValueError('Extra compressed source bytes')
        sock.shutdown(socket.SHUT_WR);state.update(status='LOSSLESS_SENSOR_BYTES_SENT',send_seconds=time.monotonic()-began)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if sock:sock.close()
        report.write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


def receive(proof,stream_proof,headers,address,native_address,report):
    p,hd=validate(proof,stream_proof,headers);report=Path(report)
    if report.exists():raise ValueError('Fresh lossless bridge report required')
    codec=Codec('lz4');listener=sock=native=None;state=dict(status='STARTING',pid=os.getpid(),codec='lz4',codec_version=codec.version,frames=0,raw_source_sha256_declared=p['raw_source_sha256'],archive_sha256=p['archive_sha256'],proof_sha256=sha(proof),helper_sha256=sha(__file__),codec_wrapper_sha256=sha(Path(__file__).with_name('sensor_compression.py')),scope='KV260 PS lossless byte bridge only; actual raw pixel/CRC checks remain in native consumer. Not live UVC or final standalone acceptance.')
    try:
        host,port=endpoint(address);family=socket.AF_INET6 if ':' in host else socket.AF_INET;listener=socket.socket(family,socket.SOCK_STREAM);listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        target=socket.getaddrinfo(host,port,family,socket.SOCK_STREAM,0,socket.AI_NUMERICHOST|socket.AI_NUMERICSERV)[0][4];listener.bind(target);listener.listen(1);listener.settimeout(240);sock,_=listener.accept();sock.settimeout(30)
        if PRELUDE.unpack(exact(sock,PRELUDE.size))!=(b'ORBCLZ41',bytes.fromhex(p['archive_sha256']),FRAME_COUNT):raise ValueError('Explicit compressed source prelude differs')
        native=connect(native_address,180);native.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);native.sendall(struct.pack('<8s32sQ',b'ORBSTRM1',bytes.fromhex(p['raw_source_sha256']),FRAME_COUNT));sock.sendall(b'ORBRDY01');began=time.monotonic();cpu_began=time.process_time();decode_ns=0
        for i,row in enumerate(p['packets']):
            if exact(sock,BLOCK.size)!=BLOCK.pack(i,RAW_BYTES,row['compressed_bytes']):raise ValueError('Compressed source header/order differs')
            data=exact(sock,row['compressed_bytes'])
            if zlib.crc32(data)!=row['compressed_crc32']:raise ValueError('Compressed source checksum differs')
            started=time.perf_counter_ns();raw=codec.decode(data);decode_ns+=time.perf_counter_ns()-started
            if raw[:32]!=hd[i*32:(i+1)*32]:raise ValueError('Decoded original identity differs')
            native.sendall(raw);state['frames']=i+1
        if sock.recv(1):raise ValueError('Extra compressed source packets')
        native.shutdown(socket.SHUT_WR);state.update(status='LOSSLESS_SENSOR_BRIDGE_DRAINED',seconds=time.monotonic()-began,decode_seconds=decode_ns/1e9,cpu_seconds=time.process_time()-cpu_began,all_declared_packets_forwarded=True)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        for item in (native,sock,listener):
            if item:item.close()
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare')
    for k in ('raw','stream_proof','headers','output'):a.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    for mode in ('send','receive'):
        a=sub.add_parser(mode)
        for k in ('proof','stream_proof','headers','report'):a.add_argument('--'+k.replace('_','-'),type=Path,required=True)
        a.add_argument('--address',required=True)
        if mode=='send':a.add_argument('--archive',type=Path,required=True)
        else:a.add_argument('--native-address',required=True)
    args=vars(p.parse_args());mode=args.pop('mode');globals()[mode](**args)
