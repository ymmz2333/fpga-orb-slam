"""Independent stdlib/zlib CRC vectors, including every tail and alignment."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import zlib


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rng=random.Random(0x43524332)
    data=rng.randbytes(2073600+64)
    rows=[(offset,n) for offset in range(64) for n in range(32)]
    rows += [(rng.randrange(64),rng.randrange(32,32769)) for _ in range(2048)]
    rows += [(offset,n) for offset in range(64) for n in (65535,65536,691200,1382400,2073600)]
    paths=[output/'vectors.bin',output/'expected.csv']
    paths[0].write_bytes(data)
    paths[1].write_bytes(('offset,length,crc32\n'+''.join(f'{o},{n},{zlib.crc32(data[o:o+n])}\n' for o,n in rows)).encode())
    proof=dict(status='INDEPENDENT_IEEE_CRC_FIXTURE',cases=len(rows),zlib=zlib.ZLIB_VERSION,
               source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               files_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (output/'FIXTURE.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(status=proof['status'],cases=len(rows))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
