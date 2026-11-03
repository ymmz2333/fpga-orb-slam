import hashlib,json,struct
from pathlib import Path
import pytest
from orb60.kv260.lossless_sensor_stream import validate,verify_receipt,FRAME_COUNT,RAW_BYTES,exact


def fixture(tmp_path):
    headers=b''.join(struct.pack('<8sQQII',b'ORBYUYV1',i,1000+i,123+i,456+i) for i in range(FRAME_COUNT));hp=tmp_path/'headers.bin';hp.write_bytes(headers)
    h=hashlib.sha256(headers).hexdigest();s=dict(status='PACKED_SENSOR_BYTES_SEALED',data_sha256='a'*64);sp=tmp_path/'STREAM.json';sp.write_text(json.dumps(s))
    p=dict(status='LOSSLESS_RAW_SENSOR_ARCHIVE_SEALED',codec='lz4',frames=FRAME_COUNT,raw_bytes_per_frame=RAW_BYTES,raw_source_sha256=s['data_sha256'],stream_proof_sha256=hashlib.sha256(sp.read_bytes()).hexdigest(),headers_sha256=h,archive_sha256='b'*64,
           packets=[dict(frame=i,compressed_bytes=100,compressed_crc32=123,raw_header_hex=headers[i*32:(i+1)*32].hex()) for i in range(FRAME_COUNT)])
    pp=tmp_path/'SOURCE.json';pp.write_text(json.dumps(p));return pp,sp,hp,p


def test_complete_lossless_source_and_receipt_pairing(tmp_path):
    pp,sp,hp,p=fixture(tmp_path);proof,headers=validate(pp,sp,hp);assert len(headers)==FRAME_COUNT*32 and proof['codec']=='lz4'
    r=dict(status='LOSSLESS_SENSOR_BRIDGE_DRAINED',codec='lz4',frames=FRAME_COUNT,all_declared_packets_forwarded=True,raw_source_sha256_declared='a'*64,archive_sha256='b'*64,proof_sha256=hashlib.sha256(pp.read_bytes()).hexdigest())
    rp=tmp_path/'RECEIPT.json';rp.write_text(json.dumps(r));assert verify_receipt(pp,sp,hp,rp)['frames']==FRAME_COUNT
    r['frames']-=1;rp.write_text(json.dumps(r))
    with pytest.raises(ValueError):verify_receipt(pp,sp,hp,rp)


@pytest.mark.parametrize('field,value',[('frame',1),('compressed_bytes',0),('compressed_bytes',RAW_BYTES*2),('raw_header_hex','00'*32)])
def test_corrupt_packet_identity_size_and_order_rejected(tmp_path,field,value):
    pp,sp,hp,p=fixture(tmp_path);p['packets'][0][field]=value;pp.write_text(json.dumps(p))
    with pytest.raises(ValueError):validate(pp,sp,hp)


def test_wrong_raw_source_and_missing_frames_rejected(tmp_path):
    pp,sp,hp,p=fixture(tmp_path);p['raw_source_sha256']='c'*64;pp.write_text(json.dumps(p))
    with pytest.raises(ValueError):validate(pp,sp,hp)
    p['raw_source_sha256']='a'*64;p['packets'].pop();pp.write_text(json.dumps(p))
    with pytest.raises(ValueError):validate(pp,sp,hp)


def test_socket_short_reads_preserve_exact_bytes_and_eof_fails():
    class Source:
        def __init__(self,parts):self.parts=iter(parts)
        def recv(self,n):return next(self.parts,b'')
    assert exact(Source([b'a',b'b',b'cd']),4)==b'abcd'
    with pytest.raises(ValueError):exact(Source([b'a']),2)
