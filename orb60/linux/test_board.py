"""Real-board golden gate. Never accepts the server's replay backend."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
from client import Client


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=5600)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--descriptors',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--repeat',type=int,default=3)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    image_info=json.loads((a.images/'vectors.json').read_text())
    descriptor_info=json.loads((a.descriptors/'vectors.json').read_text())
    expected=[]
    for frame in range(3):
        records=bytearray()
        for level in range(8):
            case=descriptor_info['cases'][frame*8+level]
            data=(a.descriptors/(case['name']+'_features.bin')).read_bytes()
            assert hashlib.sha256(data).hexdigest()==descriptor_info['sha256'][case['name']+'_features.bin']
            records.extend(data[case['offset']*64:(case['offset']+case['completed'])*64])
        expected.append(bytes(records))
    client=Client(a.host,a.port);runs=[]
    try:
        for n in range(a.repeat*3):
            frame=n%3;pixels=(a.images/f'f{frame}_l0_input.bin').read_bytes()
            result,payload=client.extract(pixels,100+n,1000000000+33333333*n,n%2)
            assert not result['simulated'] and result['records']==expected[frame],f'exact features frame{frame}'
            for level in range(8):
                assert result['counts'][level]==image_info['cases'][frame*8+level]['selected']
            prefix=a.output/f'frame_{n:03d}'
            prefix.with_suffix('.payload').write_bytes(payload)
            meta={k:v for k,v in result.items() if k not in ('records','stats')}
            meta.update(input_frame=frame,feature_sha256=hashlib.sha256(result['records']).hexdigest(),exact=True)
            prefix.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n');runs.append(meta)
            print(f"BOARD_EXACT frame={n} input={frame} count={result['count']} engine_ms={result['engine_ns']/1e6:.3f} roundtrip_ms={result['roundtrip_ns']/1e6:.3f}",flush=True)
    finally:
        client.close()
    summary=dict(status='PASS',scope='physical ACZ7015 Ethernet +150MHz PL, full exact records against independent golden',runs=runs)
    for field in ('engine_ns','input_copy_ns','roundtrip_ns'):
        values=[r[field] for r in runs]
        summary[field]=dict(min=min(values),mean=statistics.mean(values),max=max(values))
    (a.output/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('PHYSICAL_BOARD_FULL_RECORD_EXACT_PASS',flush=True)


if __name__=='__main__':
    main()
