"""Real native TCP/state/map integration plus frozen physical-record transport checks.

The native server's camera/pose observations are explicit test fixtures, not board
measurements. Production zynq-demo has no fixture or CPU ORB mode.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import zlib

from orb60.demo_bridge.calibration import cropped, encode, read, fingerprint
from orb60.demo_bridge.protocol import Packet, Kind, IMAGE_BYTES, receive, connect, command, validate_frame
from orb60.demo_bridge.map_bundle import seal, validate, upload, parse_manifest, REQUIRED
from orb60.demo_bridge.install_rk import patch_feature_io

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'orb60/build/demo_bridge'
NATIVE = OUT / 'native/test-bridge.exe'


def write_rows(path, values):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)


def bundle(path):
    path.mkdir()
    camera = ROOT / 'orb60/demo_bridge/config/camera_orb.csv'
    k = read(camera.read_bytes())
    points = [dict(point_id=i+1, x=.1*i, y=.03*i, z=2+.1*i, observations=4) for i in range(12)]
    keys = []
    for i in range(4):
        row = dict(keyframe_id=i, slam_frame_id=i, timestamp_ns=1000000000+i*33333333,
                   **{name: k[name] for name in ('fx','fy','cx','cy','d0','d1','d2','d3','d4')})
        row.update({'twc_%d%d' % (r,c): int(r==c) for r in range(4) for c in range(4)})
        keys.append(row)
    obs = [dict(keyframe_id=kid, point_id=p['point_id'], u=400+p['point_id'], v=300,
                raw_u=400+p['point_id'], raw_v=300, octave=0, descriptor_row=kid*len(points)+i)
           for kid in range(4) for i,p in enumerate(points)]
    write_rows(path/'points.csv', points)
    write_rows(path/'keyframes.csv', keys)
    write_rows(path/'observations.csv', obs)
    reps = b''.join(bytes([i])*32 for i in range(12))
    (path/'representative_descriptors.bin').write_bytes(reps)
    (path/'observation_descriptors.bin').write_bytes(reps*4)
    seal(path,camera,7)
    return camera


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


class Gate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gate_',dir=OUT)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_calibration_crop_and_float32_export(self):
        source = read((ROOT/'orb60/demo_bridge/config/camera_source.csv').read_bytes())
        work = cropped(source)
        self.assertEqual(work['cx'],533.5148113045461)
        self.assertEqual(work['fx'],source['fx'])
        self.assertEqual(work['d4'],source['d4'])
        camera = bundle(self.root/'map')
        keys=list(csv.DictReader((self.root/'map/keyframes.csv').open()))
        for key in keys:
            for name in ('fx','fy','cx','cy','d0','d1','d2','d3','d4'):
                key[name]=struct.unpack('<f',struct.pack('<f',float(key[name])))[0]
        write_rows(self.root/'map/keyframes.csv',keys)
        seal(self.root/'map',camera,7)
        keys[0]['cx']=float(keys[0]['cx'])+1
        write_rows(self.root/'map/keyframes.csv',keys)
        with self.assertRaises(ValueError):seal(self.root/'map',camera,7)

    def test_python_cpp_wire_and_bad_headers(self):
        rng=random.Random(7015)
        for n in (0,1,55,64,4097,IMAGE_BYTES):
            p=Packet(Kind.FRAME,7,11,1234567890123,4,3,0,rng.randbytes(n))
            encoded=p.encode()
            self.assertEqual(Packet.decode(encoded),p)
            (self.root/'in').write_bytes(encoded)
            subprocess.run([NATIVE,'--wire',self.root/'in',self.root/'out'],check=True,capture_output=True,timeout=15)
            self.assertEqual((self.root/'out').read_bytes(),encoded)
        bad=bytearray(p.encode());bad[-1]^=1
        with self.assertRaises(ValueError):Packet.decode(bad)
        bad=bytearray(p.encode());struct.pack_into('<I',bad,40,0xffffffff)
        with self.assertRaises(ValueError):Packet.decode(bad)
        with self.assertRaises(ValueError):Packet.decode(p.encode()[:-1])
        a,b=socket.socketpair();a.settimeout(3);b.settimeout(3)
        def send_fragments():
            try:
                wire=Packet(Kind.STATUS,body=b'fragmented').encode()
                for i in range(0,len(wire),3):a.sendall(wire[i:i+3])
            finally:a.close()
        t=threading.Thread(target=send_fragments);t.start()
        with b:self.assertEqual(receive(b).body,b'fragmented')
        t.join(timeout=4)
        self.assertFalse(t.is_alive(),'fragment sender did not terminate')

    def test_frozen_gray_and_physical_record_bytes(self):
        data=ROOT/'orb60/build/handoff/zynq7015_20261022'
        if not data.is_dir():
            fixtures=Path(__file__).parent/'fixtures';report=json.loads((fixtures/'historical.json').read_text())
            for row in report['frames']:
                raw=(fixtures/row['file']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),row['packet_sha256'])
                (self.root/'in').write_bytes(raw);subprocess.run([NATIVE,'--wire',self.root/'in',self.root/'out'],check=True,capture_output=True,timeout=15)
                gray,payload=validate_frame(Packet.decode((self.root/'out').read_bytes()))
                self.assertEqual(hashlib.sha256(gray).hexdigest(),row['gray_sha256'])
                self.assertEqual(hashlib.sha256(payload[128:-1024]).hexdigest(),row['records_sha256'])
            return
        import av
        with (data/'golden/frames.csv').open() as f:rows=list(csv.DictReader(f))[:3]
        bysource={int(row['source_frame_index']):row for row in rows}
        tested=[]
        with av.open(str(data/'testdata/video.mp4')) as video,(data/'golden/features.bin').open('rb') as records,(data/'golden/runtime.bin').open('rb') as runtime:
            for index,image in enumerate(video.decode(video.streams.video[0])):
                if index not in bysource:continue
                row=bysource[index];fid=int(row['frame_index']);count=int(row['count']);gray=image.to_ndarray(format='gray').tobytes()
                self.assertEqual(hashlib.sha256(gray).hexdigest(),row['gray_sha256'])
                records.seek(int(row['record_offset'])*64);raw=records.read(count*64)
                runtime.seek(fid*1152);meta=runtime.read(128);stats=runtime.read(1024)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['records_sha256'])
                packet=Packet(Kind.FRAME,41,fid,int(row['timestamp_ns']),count,zlib.crc32(gray),0,gray+meta+raw+stats)
                (self.root/'in').write_bytes(packet.encode())
                subprocess.run([NATIVE,'--wire',self.root/'in',self.root/'out'],check=True,capture_output=True,timeout=15)
                received=Packet.decode((self.root/'out').read_bytes());decoded_gray,result=validate_frame(received)
                self.assertEqual(decoded_gray,gray);self.assertEqual(result[128:128+count*64],raw)
                tested.append(dict(frame=fid,count=count,gray_sha256=row['gray_sha256'],records_sha256=row['records_sha256']))
                if len(tested)==3:break
        self.assertEqual(len(tested),3)
        (OUT/'golden_transport.json').write_text(json.dumps(dict(scope='Transport of historical physical records, no new PL run',frames=tested),indent=2)+'\n')

    def test_map_manifest_geometry_and_corruption(self):
        camera=bundle(self.root/'map');path=self.root/'map'
        self.assertEqual(validate(path,camera.read_bytes())['points'],12)
        manifest=(path/'manifest.txt').read_bytes()
        with self.assertRaises(ValueError):parse_manifest(manifest,b'0'*64)
        bad=manifest.replace(b'points.csv',b'../points.csv')
        with self.assertRaises(ValueError):parse_manifest(bad,fingerprint(camera.read_bytes()))
        data=(path/'representative_descriptors.bin').read_bytes();(path/'representative_descriptors.bin').write_bytes(data[:-1])
        with self.assertRaises(ValueError):validate(path,camera.read_bytes())

    def test_actual_runtime_drain_install_disconnect_preserve(self):
        camera=bundle(self.root/'map');store=self.root/'store';stream_port,control_port,map_port=free_port(),free_port(),free_port()
        logfile=(self.root/'server.log').open('w')
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        child=subprocess.Popen([NATIVE,'--serve-test',store,camera,str(stream_port),str(control_port),str(map_port),'25'],stdout=logfile,stderr=subprocess.STDOUT,creationflags=flags)
        def status():return command('127.0.0.1',control_port,'status')
        def wait_for(predicate):
            end=time.monotonic()+5
            while time.monotonic()<end:
                try:
                    s=status()
                    if predicate(s):return s
                except (OSError,ConnectionError):pass
                time.sleep(.02)
            raise AssertionError('Runtime did not reach expected state; last='+str(locals().get('s')))
        def open_stream():
            peer=connect('127.0.0.1',stream_port)
            peer.sendall(Packet(Kind.HELLO,body=fingerprint(camera.read_bytes()).encode()).encode())
            self.assertEqual(receive(peer).kind,Kind.HELLO)
            return peer
        def ack(peer,p):peer.sendall(Packet(Kind.ACK,p.session,p.frame,p.stamp).encode())
        try:
            wait_for(lambda s: s['mode']=='WAITING')
            with open_stream() as peer:
                session=command('127.0.0.1',control_port,'start')['session']
                p=receive(peer);time.sleep(.1)
                bounded=status();self.assertLessEqual(bounded['sent']-bounded['acknowledged'],3);self.assertLessEqual(bounded['queue_high'],3)
                ack(peer,p)
                repeated=command('127.0.0.1',control_port,'start')
                self.assertEqual(repeated['session'],session)
                command('127.0.0.1',control_port,'finalize')
                while True:
                    p=receive(peer);ack(peer,p)
                    if p.kind==Kind.END:break
            drained=wait_for(lambda s:s['drained'])
            self.assertEqual(drained['sent'],drained['acknowledged'])
            receipt=upload(self.root/'map','127.0.0.1',map_port)
            local=wait_for(lambda s:s['mode']=='LOCAL' and s['ready_to_disconnect'])
            self.assertEqual(local['map_version'],receipt['version'])
            pointer=(store/'current').read_bytes()
            native=(store/'versions'/receipt['version']/'map.zmap').read_bytes()
            self.assertEqual(zlib.crc32(native[:-4]),struct.unpack_from('<I',native,len(native)-4)[0])
            self.assertEqual(struct.unpack_from('<II',native,92),(12,4))
            # Independent native-map point/descriptor parser: no fitting or rescaling.
            for i in range(12):
                off=100+i*69
                self.assertEqual(struct.unpack_from('<Q',native,off)[0],i+1)
                self.assertEqual(struct.unpack_from('<3d',native,off+8),(.1*i,.03*i,2+.1*i))
                self.assertEqual(native[off+32:off+64],bytes([i])*32)
            # Closing all mapping connections after handover leaves local mode alone.
            self.assertEqual(status()['mode'],'LOCAL')
            manifest_path=store/'versions'/receipt['version']/'manifest.txt'
            original_manifest=manifest_path.read_bytes()
            manifest_path.write_bytes(original_manifest.replace(b' 7 12 4\n',b' 8 12 4\n'))
            check=subprocess.run([NATIVE,'--current-test',store,camera],capture_output=True,timeout=10)
            self.assertNotEqual(check.returncode,0,'Reboot load must reject changed manifest identity')
            manifest_path.write_bytes(original_manifest)
            check=subprocess.run([NATIVE,'--current-test',store,camera],capture_output=True,timeout=10)
            self.assertEqual(check.returncode,0)
            with open_stream() as peer:
                command('127.0.0.1',control_port,'start');p=receive(peer)
                # Disconnect without ACK: must fail, never silently select old local map.
            wait_for(lambda s:s['mode']=='ERROR')
            self.assertEqual((store/'current').read_bytes(),pointer)
            command('127.0.0.1',control_port,'relocalize');wait_for(lambda s:s['mode']=='LOCAL')
            with open_stream() as peer:
                command('127.0.0.1',control_port,'start');p=receive(peer);ack(peer,p)
                command('127.0.0.1',control_port,'finalize')
                while True:
                    p=receive(peer);ack(peer,p)
                    if p.kind==Kind.END:break
            wait_for(lambda s:s['drained'])
            with connect('127.0.0.1',map_port) as peer:
                peer.sendall(Packet(Kind.MAP_BEGIN,body=(self.root/'map/manifest.txt').read_bytes()).encode());self.assertEqual(receive(peer).kind,Kind.STATUS)
                # The map connection intentionally remains open. Control must still respond.
                began=time.monotonic();stopped=command('127.0.0.1',control_port,'stop')
                self.assertLess(time.monotonic()-began,2);self.assertEqual(stopped['mode'],'STOPPED')
            wait_for(lambda s:s['mode']=='STOPPED')
            self.assertEqual((store/'current').read_bytes(),pointer)
            command('127.0.0.1',control_port,'relocalize')
            wait_for(lambda s:s['mode']=='LOCAL')
            with open_stream() as peer:
                command('127.0.0.1',control_port,'start');p=receive(peer);ack(peer,p)
                command('127.0.0.1',control_port,'finalize')
                while True:
                    p=receive(peer);ack(peer,p)
                    if p.kind==Kind.END:break
            wait_for(lambda s:s['drained'])
            with connect('127.0.0.1',map_port) as peer:
                peer.sendall(Packet(Kind.MAP_BEGIN,body=(self.root/'map/manifest.txt').read_bytes()).encode());self.assertEqual(receive(peer).kind,Kind.STATUS)
                peer.sendall(Packet(Kind.MAP_FILE,body=b'points.csv\nCORRUPTED').encode());self.assertEqual(receive(peer).kind,Kind.ERROR)
            wait_for(lambda s:s['mode']=='ERROR')
            self.assertEqual((store/'current').read_bytes(),pointer)
        finally:
            child.terminate();child.wait(timeout=5);logfile.close()
            shutil.copy2(self.root/'server.log',OUT/'last_runtime_server.log')

    def test_rk_injection_patch_against_retained_source(self):
        source=ROOT/'orb60/build/linux/frame_pipeline_20261021/orb60-patch-lkmzw_b5/src/FeatureIO.cc'
        if not source.is_file():source=Path(__file__).parent/'fixtures/FeatureIO.retained.cc'
        text=source.read_text();patched=patch_feature_io(text)
        self.assertIn('BridgeFeatures::consume(stats.timestamp_ns,image',patched)
        self.assertIn('mode=="fpga-camera" || PipelineActive()',patched)
        self.assertEqual(patch_feature_io(patched),patched)
        self.assertNotIn('BridgeFeatures',text)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Gate)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
                failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors],
                scope='Native protocol/state/map tests and transport of frozen PL records; no new hardware or RK tracking run',
                arm_build='NOT_RUN',rk_build='NOT_RUN',board_acceptance='NOT_RUN')
    (OUT/'offline_gate.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
