"""Actual native socket/EOS tests; no physical PL or SLAM claim."""
import argparse,hashlib,json,select,socket,struct,subprocess,zlib
from pathlib import Path
from orb60.kv260.localization_input import Sender,header,SIZE

def run(binary,output):
    binary,output=Path(binary).resolve(),Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    camera=output/'camera.csv';camera.write_text('width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4\n960,720,700,700,480,360,0,0,0,0,0\n')
    tests=[]
    for case in ('valid','disconnect','crc','count','stamp','sequence','calibration','payload','finite_end'):
        folder=output/case;folder.mkdir();probe=socket.socket(socket.AF_INET6);probe.bind(('::1',0));port=probe.getsockname()[1];probe.close()
        args=[str(binary),str(port),str(camera),'0','8' if case=='finite_end' else '0',str(folder/'input.csv')]
        if case!='finite_end':args+=['manual']
        child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE);sender=None
        try:
            if not select.select([child.stdout],[],[],10)[0]:raise TimeoutError('Manual native source not ready')
            ready=child.stdout.readline();assert ready.startswith(b'NETWORK_CAMERA_READY ')
            sender=Sender('::1',port,camera.read_bytes(),0)
            for i in range(4):sender.send(bytes([20+i])*SIZE,i,1_000_000_000+i*20_000_000,40+i*2)
            if case=='valid':sender.finish_manual()
            elif case!='disconnect':
                h=bytearray(header(4,sender.stamp,sender.sequence,0,sender.calibration,0));h[:8]=b'ORBGRAY3';struct.pack_into('<I',h,32,0);struct.pack_into('<I',h,60,1)
                if case=='count':struct.pack_into('<Q',h,16,3)
                if case=='stamp':struct.pack_into('<Q',h,24,sender.stamp+1)
                if case=='sequence':struct.pack_into('<I',h,52,999)
                if case=='calibration':h[64]^=1
                if case=='payload':struct.pack_into('<I',h,32,SIZE)
                struct.pack_into('<I',h,56,0);struct.pack_into('<I',h,56,zlib.crc32(h))
                if case=='crc':h[56]^=1
                sender.sock.sendall(h)
            sender.close();sender=None
            rest,error=child.communicate(timeout=10);stdout=ready+rest
            (folder/'stdout.log').write_bytes(stdout);(folder/'stderr.log').write_bytes(error)
            if case=='valid':
                assert child.returncode==0 and b'NETWORK_CAMERA_INPUT_PASS' in stdout
                assert json.loads((folder/'input.csv.end.json').read_text())=={'status':'OPERATOR_STREAM_END_RECEIVED','frames':4}
            else:
                assert child.returncode==1 and b'NETWORK_CAMERA_FAULT_LATCH_PASS' in stdout
                assert not (folder/'input.csv.end.json').exists()
            tests.append(dict(case=case,status='PASS'))
        finally:
            if sender:sender.close()
            if child.poll() is None:child.terminate();child.wait(timeout=5)
    result=dict(status='NATIVE_MANUAL_NETWORK_PROTOCOL_GATE_PASS',hardware_test=False,tests=tests,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (output/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
