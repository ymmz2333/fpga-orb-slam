"""Exercise the compiled C server, including fragmented and corrupt requests."""
import argparse
import importlib.util
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import zlib

spec=importlib.util.spec_from_file_location('client',Path(__file__).with_name('client.py'))
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


def exercise(server):
    pixels=bytes((i*17+i//960)%256 for i in range(960*720))
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'replay.bin'
        payload=bytearray(128+64+1024)
        struct.pack_into('<8I',payload,0,1,0,0,0,0,0,0,0)
        struct.pack_into('<8I',payload,32,0,1,1,1,1,1,1,1)
        struct.pack_into('<5I2iI',payload,128,100,80,200,0,31,-12345,67890,31*737280)
        payload[160:192]=bytes(range(32));path.write_bytes(payload)
        for case in ('fragmented','bad_crc','bad_width','bad_budget'):
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            proc=subprocess.Popen([str(server),'--bind','127.0.0.1','--port',str(port),'--replay',str(path),'--once'],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                assert 'READY' in proc.stdout.readline()
                with socket.create_connection(('127.0.0.1',port),5) as sock:
                    header=bytearray(client.request_header(7,123456789,1,pixels))
                    if case=='bad_crc':header[56]^=1
                    if case=='bad_width':struct.pack_into('<I',header,32,1280)
                    if case=='bad_budget':struct.pack_into('<I',header,44,5000)
                    for part in (header[:3],header[3:17],header[17:]):sock.sendall(part)
                    if case not in ('bad_width','bad_budget'):
                        for start in range(0,len(pixels),1093):sock.sendall(pixels[start:start+1093])
                    reply=client.receive(sock,64);fields=client.HEADER.unpack(reply)
                    result=client.receive(sock,fields[-4])
                    assert zlib.crc32(result)==fields[-2]
                    if case=='fragmented':
                        decoded=client.decode(reply,result,7,123456789,1,True)
                        assert decoded['count']==1 and decoded['simulated']
                        try:client.decode(reply,result,7,123456789,1)
                        except ValueError:pass
                        else:raise AssertionError('simulated result accepted as hardware')
                        packet=client.b1_packet(decoded)
                        assert packet[:8]==b'ORBFEAT\0' and len(packet)==128 and packet[96:]==bytes(range(32))
                        assert struct.unpack_from('<ffi',packet,64)==(100.0,80.0,0)
                        # Reuse the same connection for a second frame, with a distinct identity.
                        sock.sendall(client.request_header(8,123456790,0,pixels)+pixels)
                        rep=client.receive(sock,64);body=client.receive(sock,client.HEADER.unpack(rep)[-4])
                        assert client.decode(rep,body,8,123456790,0,True)['count']==1
                    else:assert fields[-3]!=0
                stdout,stderr=proc.communicate(timeout=5)
                assert proc.returncode==0,(stdout,stderr)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
    print('C_SERVER_FRAGMENT_CRC_SHAPE_BUDGET_REUSE_SIMULATION_GUARD_B1_PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--server',type=Path,required=True)
    exercise(p.parse_args().server.resolve())
