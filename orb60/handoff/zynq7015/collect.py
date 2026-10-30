"""Capture physical PL results, refusing any input/count/historical-record mismatch."""
import argparse
import importlib.util
from pathlib import Path
import time
import zlib
import cv2
from common import rows,sha,save,write_rows

def main():
    p=argparse.ArgumentParser()
    for name in ('dataset','history','wire-client','video','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--host',required=True);a=p.parse_args()
    host,port=a.host[1:].split(']:',1) if a.host.startswith('[') else a.host.rsplit(':',1)
    spec=importlib.util.spec_from_file_location('physical_wire',str(a.wire_client));wire=importlib.util.module_from_spec(spec);spec.loader.exec_module(wire)
    historical={}
    for line in a.history.read_text().splitlines():
        if line.startswith('FPGA_ORB_NET '):
            item=dict(s.split('=',1) for s in line.split()[1:] if '=' in s)
            historical[int(item['frame'])]=item
    source=rows(a.dataset/'frames.csv')
    if len(source)!=2273 or len(historical)!=2273:raise ValueError('Expected the exact frozen2273-frame sequence')
    if sha(a.video)!='c2ab71867980667111e365ea49ddbc618baa8400b3a5723d10652b204f76a7f4':raise ValueError('Original video SHA mismatch')
    a.output.mkdir(parents=True,exist_ok=False);start=time.monotonic();index=[];offset=0
    original_decode=wire.decode
    def decode_with_header(header,*args,**kwargs):
        result=original_decode(header,*args,**kwargs);result['_wire_header']=header;return result
    wire.decode=decode_with_header
    client=wire.Client(host,int(port),timeout=10,allow_simulated=False)
    try:
        with (a.output/'features.bin.part').open('wb') as binary,(a.output/'runtime.bin.part').open('wb') as runtime,(a.output/'headers.bin.part').open('wb') as headers:
            for i,row in enumerate(source):
                path=a.dataset/row['image']
                if sha(path)!=row['sha256']:raise ValueError('Prepared PNG hash mismatch: '+str(path))
                gray=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
                if gray is None or gray.shape!=(720,960):raise ValueError('Invalid working image: '+str(path))
                data=gray.tobytes();old=historical[i+1];role=int(old['role'])
                result,payload=client.extract(data,i+1,int(row['timestamp_ns']),role)
                crc=zlib.crc32(result['records'])
                if result['simulated'] or result['count']!=int(old['count']) or crc!=int(old['record_crc']):
                    raise ValueError('Historical FPGA record mismatch at frame%d'%i)
                binary.write(result['records']);runtime.write(payload[:128]+result['stats'])
                headers.write(result['_wire_header'])
                index.append(dict(frame_index=i,source_frame_index=int(row['source_frame_index']),timestamp_ns=int(row['timestamp_ns']),
                    mp4_pts_s=row['mp4_pts_s'],role=role,count=result['count'],record_offset=offset,record_crc32=crc,
                    records_sha256=__import__('hashlib').sha256(result['records']).hexdigest(),
                    gray_sha256=__import__('hashlib').sha256(data).hexdigest(),png_sha256=row['sha256'],
                    engine_ns=result['engine_ns'],roundtrip_ns=result['roundtrip_ns']))
                offset+=result['count']
                if (i+1)%100==0:print('CAPTURE',i+1,'of',len(source),'seconds',round(time.monotonic()-start,2),flush=True)
        for name in ('features.bin','runtime.bin','headers.bin'):(a.output/(name+'.part')).replace(a.output/name)
        write_rows(a.output/'frames.csv',index)
        save(a.output/'capture_acceptance.json',dict(status='PASS',backend='physical_fpga',frames=len(index),
             historical_count_crc_matches=len(index),cpu_orb_calls=0,records=offset,seconds=time.monotonic()-start,
             video_sha256=sha(a.video),features_sha256=sha(a.output/'features.bin'),runtime_sha256=sha(a.output/'runtime.bin'),
             headers_sha256=sha(a.output/'headers.bin'),
             source_manifest_sha256=sha(a.dataset/'frames.csv'),wire_client_sha256=sha(a.wire_client),
             history_sha256=sha(a.history),opencv=cv2.__version__))
        print('CAPTURE_PASS',len(index),'records',offset,flush=True)
    finally:client.close()

if __name__=='__main__':main()
