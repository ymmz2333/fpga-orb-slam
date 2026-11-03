"""Independent bytewise Python bit_count golden, including extreme patterns."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import struct


def prepare(output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh fixture required')
    rng=random.Random(7015260);cases=[(bytes(32),bytes(32)),(bytes(32),b'\xff'*32),(b'\xff'*32,b'\xff'*32),(b'\x55'*32,b'\xaa'*32)]
    for _ in range(10000-len(cases)):cases.append((rng.randbytes(32),rng.randbytes(32)))
    raw=b''.join(a+b+struct.pack('<I',sum((x^y).bit_count() for x,y in zip(a,b))) for a,b in cases)
    output.write_bytes(raw);proof=dict(cases=len(cases),sha256=hashlib.sha256(raw).hexdigest(),golden='Python bytewise xor.bit_count; independent of NEON and retained SWAR')
    output.with_suffix('.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);prepare(p.parse_args().output)
