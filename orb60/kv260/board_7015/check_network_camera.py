"""Exercise the actual C++ input adapter over sockets; no PL or SLAM claim."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import select
import socket
import struct
import subprocess
import time
import zlib
from orb60.kv260.localization_input import header,validate_ack,SIZE
from orb60.linux.client import receive


def _run(binary,output):
    binary=Path(binary).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    calibration=output/'camera.csv';calibration.write_text('width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4\n960,720,700,700,480,360,0,0,0,0,0\n')
    digest=hashlib.sha256(calibration.read_bytes()).hexdigest();results=[]
    cases=('camera','recorded','header_crc','pixel_crc','calibration','mode','frame','stamp','raw_sequence','size','truncated')
    for case in cases:
        mode=int(case=='recorded');folder=output/case;folder.mkdir();journal=folder/'input.csv'
        probe=socket.socket(socket.AF_INET6);probe.bind(('::1',0));port=probe.getsockname()[1];probe.close()
        child=subprocess.Popen([str(binary),str(port),str(calibration),str(mode),'4',str(journal)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        lines=[];sock=None
        try:
            if not select.select([child.stdout],[],[],10)[0]:raise TimeoutError('Native network source readiness timed out')
            first=child.stdout.readline();lines.append(first)
            if not first.startswith(b'NETWORK_CAMERA_READY '):raise RuntimeError('Native source not ready')
            sock=socket.create_connection(('::1',port),5);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            for i in range(4):
                raw=bytes((n+i)&255 for n in range(256))*(SIZE//256);crc=zlib.crc32(raw)
                seq=i if mode else (40,43,44,48)[i];stamp=1000000000+i*20000000
                h=bytearray(header(i,stamp,seq,crc,digest,mode));body=raw
                if i==1:
                    if case=='calibration':h[64]^=1
                    if case=='mode':struct.pack_into('<I',h,48,1)
                    if case=='frame':struct.pack_into('<Q',h,16,7)
                    if case=='stamp':struct.pack_into('<Q',h,24,1000000000)
                    if case=='raw_sequence':struct.pack_into('<I',h,52,40)
                    if case=='size':struct.pack_into('<I',h,32,SIZE+1)
                    if case not in ('camera','recorded'):
                        struct.pack_into('<I',h,56,0);struct.pack_into('<I',h,56,zlib.crc32(h))
                    if case=='header_crc':h[56]^=1
                    if case=='pixel_crc':body=bytes([body[0]^1])+body[1:]
                    if case=='truncated':body=body[:17]
                try:
                    sock.sendall(h[:9]);sock.sendall(h[9:]);sock.sendall(body)
                    if i==1 and case=='truncated':sock.close();sock=None;break
                    validate_ack(receive(sock,32),i,stamp,crc)
                except (OSError,ValueError,ConnectionError):
                    if case in ('camera','recorded'):raise
                    break
            if sock:sock.close();sock=None
            rest,error=child.communicate(timeout=10);stdout=b''.join(lines)+rest
            (folder/'stdout.log').write_bytes(stdout);(folder/'stderr.log').write_bytes(error)
            if case in ('camera','recorded'):
                if child.returncode or b'NETWORK_CAMERA_INPUT_PASS' not in stdout:raise ValueError('Valid native network source failed')
                with journal.open(newline='') as f:rows=list(csv.DictReader(f))
                if [int(r['frame_id']) for r in rows]!=list(range(4)) or [int(r['sequence_gaps']) for r in rows]!=([0,0,0,0] if mode else [0,2,2,5]):
                    raise ValueError('Native wire identity/gaps not preserved')
            elif child.returncode!=1 or b'NETWORK_CAMERA_FAULT_LATCH_PASS' not in stdout:
                raise ValueError('Malformed network input was accepted or fault did not latch: '+case)
            if case not in ('camera','recorded'):
                expected=('pixels CRC mismatch' if case=='pixel_crc' else 'identity repeated/reordered' if case in ('frame','stamp','raw_sequence')
                          else 'socket timeout/disconnected' if case=='truncated' else 'header/format/mode/calibration mismatch')
                if expected not in error.decode():raise ValueError('Wrong native rejection reason: '+case)
            results.append(dict(case=case,exit_code=child.returncode,status='PASS'))
        finally:
            if sock:sock.close()
            if child.poll() is None:child.terminate();child.wait(timeout=5)
    report=dict(status='NATIVE_NETWORK_CAMERA_PROTOCOL_GATE_PASS',hardware_test=False,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),tests=results)
    (output/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


def run(binary,output):
    fresh=not Path(output).exists()
    try:return _run(binary,output)
    except BaseException as error:
        if fresh and Path(output).is_dir():
            (Path(output)/'RESULT.json').write_text(json.dumps(dict(status='FAILED',hardware_test=False,error=repr(error)),indent=2)+'\n')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
