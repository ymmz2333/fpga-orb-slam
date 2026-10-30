"""Retain three exact historical PL transactions and pinned dependency provenance."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import av

from .protocol import Packet,Kind
import zlib

ROOT=Path(__file__).resolve().parents[2]
BRIDGE=ROOT/'orb60/demo_bridge'


def main():
    upstream=ROOT/'zynq7015_usb_slam_20261024/source'
    dependencies=BRIDGE/'dependencies';dependencies.mkdir(exist_ok=True)
    manifest={}
    for target,key in [('native','757f3a7b25972eaa'),('arm','b1b33a5bb6b5c785')]:
        folder=upstream/'build'/('jpeg_'+target+'_'+key)
        report=json.loads((folder/'checks.json').read_text());library=folder/'libturbojpeg.a';digest=hashlib.sha256(library.read_bytes()).hexdigest()
        if report['status']!='PASS' or report['library_sha256']!=digest:raise ValueError('Pinned JPEG dependency differs')
        filename='libturbojpeg-'+target+'.a';shutil.copy2(library,dependencies/filename)
        manifest[filename]=dict(sha256=digest,upstream_version='3.2.0',target=target,scope='Retained static library, not a new build',original_report_sha256=hashlib.sha256((folder/'checks.json').read_bytes()).hexdigest())
    (dependencies/'provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    fixtures=BRIDGE/'tests/fixtures';fixtures.mkdir(exist_ok=True)
    source=ROOT/'orb60/build/linux/frame_pipeline_20261021/orb60-patch-lkmzw_b5/src/FeatureIO.cc'
    shutil.copy2(source,fixtures/'FeatureIO.retained.cc')
    data=ROOT/'orb60/build/handoff/zynq7015_20261022'
    with (data/'golden/frames.csv').open() as f:rows=list(csv.DictReader(f))[:3]
    bysource={int(row['source_frame_index']):row for row in rows};evidence=[]
    with av.open(str(data/'testdata/video.mp4')) as video,(data/'golden/features.bin').open('rb') as records,(data/'golden/runtime.bin').open('rb') as runtime:
        for index,image in enumerate(video.decode(video.streams.video[0])):
            if index not in bysource:continue
            row=bysource[index];gray=image.to_ndarray(format='gray').tobytes();fid=int(row['frame_index']);count=int(row['count'])
            records.seek(int(row['record_offset'])*64);raw=records.read(count*64);runtime.seek(fid*1152);meta=runtime.read(128);stats=runtime.read(1024)
            if hashlib.sha256(gray).hexdigest()!=row['gray_sha256'] or hashlib.sha256(raw).hexdigest()!=row['records_sha256']:raise ValueError('Historical sample SHA mismatch')
            packet=Packet(Kind.FRAME,41,fid,int(row['timestamp_ns']),count,zlib.crc32(gray),0,gray+meta+raw+stats).encode()
            filename='historical_frame_%d.packet'%fid;(fixtures/filename).write_bytes(packet)
            evidence.append(dict(row,file=filename,packet_sha256=hashlib.sha256(packet).hexdigest()))
            if len(evidence)==3:break
    (fixtures/'historical.json').write_text(json.dumps(dict(scope='Historical physical ORB captures, transport-only fixtures; never production replay',frames=evidence,feature_io_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),indent=2)+'\n')
    shutil.copy2(ROOT/'zynq7015_demo/LICENSE',BRIDGE/'LICENSE')
    print('OFFLINE_ASSETS_READY',len(evidence),'historical frames; pinned JPEG libraries')


if __name__=='__main__':main()
