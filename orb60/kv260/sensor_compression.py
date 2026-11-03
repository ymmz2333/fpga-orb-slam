"""Lossless packed-byte codec probe, not a vision or hardware benchmark."""
import argparse,ctypes,ctypes.util,hashlib,json,platform,struct,time,zlib
from pathlib import Path

RAW_BYTES=960*720*2+32
FRAME_COUNT=2297
BLOCK=struct.Struct('<III')


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


class Codec:
    def __init__(self,name):
        if name not in ('lz4','zstd'):raise ValueError('Explicit lossless codec required')
        library=ctypes.util.find_library(name)
        if not library:raise ValueError('Existing native codec library not found: '+name)
        self.lib=ctypes.CDLL(library);self.name=name
        if name=='lz4':
            self.lib.LZ4_compressBound.argtypes=[ctypes.c_int];self.lib.LZ4_compressBound.restype=ctypes.c_int
            self.lib.LZ4_compress_default.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int];self.lib.LZ4_compress_default.restype=ctypes.c_int
            self.lib.LZ4_decompress_safe.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int];self.lib.LZ4_decompress_safe.restype=ctypes.c_int
            self.lib.LZ4_versionString.restype=ctypes.c_char_p;self.version=self.lib.LZ4_versionString().decode()
        else:
            self.lib.ZSTD_compressBound.argtypes=[ctypes.c_size_t];self.lib.ZSTD_compressBound.restype=ctypes.c_size_t
            self.lib.ZSTD_compress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int];self.lib.ZSTD_compress.restype=ctypes.c_size_t
            self.lib.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t];self.lib.ZSTD_decompress.restype=ctypes.c_size_t
            self.lib.ZSTD_isError.argtypes=[ctypes.c_size_t];self.lib.ZSTD_isError.restype=ctypes.c_uint
            self.lib.ZSTD_versionString.restype=ctypes.c_char_p;self.version=self.lib.ZSTD_versionString().decode()

    def encode(self,data):
        if len(data)!=RAW_BYTES:raise ValueError('Fixed packed byte record required')
        bound=self.lib.LZ4_compressBound(len(data)) if self.name=='lz4' else self.lib.ZSTD_compressBound(len(data));out=ctypes.create_string_buffer(bound)
        n=self.lib.LZ4_compress_default(data,out,len(data),bound) if self.name=='lz4' else self.lib.ZSTD_compress(out,bound,data,len(data),1)
        if not n or (self.name=='zstd' and self.lib.ZSTD_isError(n)) or n>bound:raise ValueError('Lossless compression failed')
        return out.raw[:n]

    def decode(self,data):
        if not 0<len(data)<RAW_BYTES*2:raise ValueError('Bounded compressed record required')
        out=ctypes.create_string_buffer(RAW_BYTES)
        n=self.lib.LZ4_decompress_safe(data,out,len(data),RAW_BYTES) if self.name=='lz4' else self.lib.ZSTD_decompress(out,RAW_BYTES,data,len(data))
        if n!=RAW_BYTES:raise ValueError('Lossless decompression/size failure')
        return out.raw


def prepare(raw,proof,headers,output):
    raw,proof,headers,output=map(Path,(raw,proof,headers,output));p=json.loads(proof.read_text())
    if platform.machine()!='x86_64' or p['status']!='PACKED_SENSOR_BYTES_SEALED' or raw.stat().st_size!=p['data_bytes'] or sha(raw)!=p['data_sha256'] or sha(headers)!=p['headers_sha256']:raise ValueError('Frozen complete PC sensor-byte source required')
    output.mkdir(parents=True,exist_ok=False);indices=[round(i*(FRAME_COUNT-1)/63) for i in range(64)];hd=headers.read_bytes();report=dict(status='LOSSLESS_BYTE_SAMPLES_PREPARED',scope='64 spaced actual packed byte records only. No ORB, depth or vision computation; not system FPS.',source_sha256=p['data_sha256'],source_proof_sha256=sha(proof),rows={},codecs={})
    for name in ('lz4','zstd'):
        codec=Codec(name);encoded=0;began=time.monotonic()
        with raw.open('rb') as f,(output/(name+'.blocks')).open('wb') as out:
            for i in indices:
                f.seek(i*RAW_BYTES);data=f.read(RAW_BYTES)
                if len(data)!=RAW_BYTES or data[:32]!=hd[i*32:(i+1)*32] or zlib.crc32(data[32:])!=struct.unpack_from('<I',data,24)[0]:raise ValueError('Actual raw sample differs')
                report['rows'][str(i)]=hashlib.sha256(data).hexdigest();block=codec.encode(data)
                if codec.decode(block)!=data:raise ValueError('PC codec changed raw sample')
                out.write(BLOCK.pack(i,RAW_BYTES,len(block)));out.write(block);encoded+=len(block)+BLOCK.size
        report['codecs'][name]=dict(version=codec.version,samples=len(indices),bytes=encoded,ratio=len(indices)*RAW_BYTES/encoded,sha256=sha(output/(name+'.blocks')),prepare_seconds=time.monotonic()-began)
    (output/'PROBE.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['codecs']),flush=True)


def benchmark(inputs,output):
    inputs,output=Path(inputs),Path(output)
    if platform.machine()!='aarch64' or output.exists():raise ValueError('Actual KV260 and fresh report required')
    p=json.loads((inputs/'PROBE.json').read_text());report=dict(status='RUNNING',scope='Lossless codec component only. Timing includes output allocation/copy; source I/O and SHA checks excluded. Not system or camera FPS.',machine=platform.machine(),codecs={})
    try:
        for name,meta in p['codecs'].items():
            if sha(inputs/(name+'.blocks'))!=meta['sha256']:raise ValueError('Compressed source changed')
            blob=(inputs/(name+'.blocks')).read_bytes();blocks=[];pos=0
            while pos<len(blob):
                if len(blob)-pos<BLOCK.size:raise ValueError('Truncated block header')
                i,n,size=BLOCK.unpack_from(blob,pos);pos+=BLOCK.size
                if n!=RAW_BYTES or not 0<size<RAW_BYTES*2 or pos+size>len(blob) or str(i) not in p['rows']:raise ValueError('Invalid bounded block')
                blocks.append((i,blob[pos:pos+size]));pos+=size
            if len(blocks)!=64 or len({i for i,_ in blocks})!=64:raise ValueError('Incomplete sample coverage')
            codec=Codec(name);durations=[]
            for repeat in range(3):
                total=0
                for i,data in blocks:
                    began=time.perf_counter_ns();decoded=codec.decode(data);total+=time.perf_counter_ns()-began
                    if hashlib.sha256(decoded).hexdigest()!=p['rows'][str(i)]:raise ValueError('Actual board codec changed raw bytes')
                durations.append(total/1e9)
            report['codecs'][name]=dict(version=codec.version,samples=64,raw_byte_mismatches=0,ratio=meta['ratio'],decode_seconds=durations,median_decode_ms_per_record=sorted(durations)[1]*1000/64)
        report['status']='NATIVE_LOSSLESS_BYTE_CODEC_COMPONENT_PASS'
    except BaseException as e:report.update(status='FAILED',error=repr(e));raise
    finally:output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare')
    for k in ('raw','proof','headers','output'):a.add_argument('--'+k,type=Path,required=True)
    a=sub.add_parser('benchmark');a.add_argument('--inputs',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    args=vars(p.parse_args());mode=args.pop('mode');globals()[mode](**args)
