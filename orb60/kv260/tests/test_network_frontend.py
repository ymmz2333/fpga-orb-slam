"""Wire rejection tests with an explicit fake peer; no hardware inference claim."""
import socket
import struct
import threading
import zlib
import numpy as np
import pytest
from orb60.linux.client import HEADER,WIDTHS,HEIGHTS,receive
from orb60.kv260.network_frontend import NetworkFrontend,endpoint


def reply(fields):
    body=bytearray(128+64+1024)
    struct.pack_into('<8I',body,0,1,0,0,0,0,0,0,0)
    struct.pack_into('<8I',body,32,0,1,1,1,1,1,1,1)
    struct.pack_into('<5I2iI',body,128,100,80,200,0,7,-3,4,7*737280)
    body[160:192]=bytes(range(32))
    for level in range(8):
        at=192+128*level;n=int(level==0)
        struct.pack_into('<5I',body,at,0x600003,0,level,WIDTHS[level],HEIGHTS[level])
        struct.pack_into('<I',body,at+44,1)
        struct.pack_into('<6I',body,at+64,0x600002,0,level,n,n,int(level>0))
        struct.pack_into('<I',body,at+104,1)
    f=list(fields);f[3]=2;f[9]=1;f[10]=len(body);f[11]=0;f[12]=zlib.crc32(body);f[13]=0
    return f,body


@pytest.mark.parametrize('case',('exact','bad_crc','bad_frame','bad_stamp','simulated','oversize','truncated','bad_records'))
def test_fragmented_reply_and_closed_failure(case):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);errors=[]
    def peer():
        try:
            conn,_=listener.accept()
            with conn:
                h=HEADER.unpack(receive(conn,64));pixels=receive(conn,960*720)
                assert h[4:6]==(1,1000000001) and h[-2]==zlib.crc32(pixels)
                f,body=reply(h)
                if case=='bad_crc':f[12]^=1
                if case=='bad_frame':f[4]+=1
                if case=='bad_stamp':f[5]+=1
                if case=='simulated':f[13]=1
                if case=='oversize':f[10]=100000000
                if case=='bad_records':
                    struct.pack_into('<I',body,128+12,7);f[12]=zlib.crc32(body)
                header=HEADER.pack(*f)
                for part in (header[:3],header[3:]):conn.sendall(part)
                if case=='oversize':return
                conn.sendall(body[:17])
                if case!='truncated':conn.sendall(body[17:])
        except BaseException as error:errors.append(error)
        finally:listener.close()
    thread=threading.Thread(target=peer);thread.start()
    front=NetworkFrontend('127.0.0.1:%d'%listener.getsockname()[1])
    try:
        if case=='exact':
            payload,result=front.run(np.zeros((720,960),np.uint8),0,1000000001)
            assert len(payload)==1216 and result['count']==1 and not result['simulated']
            with pytest.raises(ValueError):front.run(np.zeros((720,960),np.uint8),0,1000000002)
        else:
            with pytest.raises((ValueError,ConnectionError)):front.run(np.zeros((720,960),np.uint8),0,1000000001)
            with pytest.raises(RuntimeError):front.run(np.zeros((720,960),np.uint8),1,1000000002)
    finally:front.close();thread.join(timeout=5)
    assert not thread.is_alive() and not errors


def test_explicit_ipv6_interface_and_invalid_endpoints():
    assert endpoint('[fe80::123%eth0]:5600')==('fe80::123%eth0',5600)
    for value in ('fe80::123:5600','[fe80::123]','host:0','host:65536',':5600','host:NaN'):
        with pytest.raises(ValueError):endpoint(value)
