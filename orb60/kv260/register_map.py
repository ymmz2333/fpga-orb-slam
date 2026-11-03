"""Read register offsets and pointer widths from the newly generated K26 HLS ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def parse_header(path):
    text=Path(path).read_text()
    offsets={key:int(value,16) for key,value in re.findall(r'^#define\s+\w+_CONTROL_ADDR_(\w+)\s+(0x[0-9a-fA-F]+)',text,re.M)}
    widths={key:int(value) for key,value in re.findall(r'^#define\s+\w+_CONTROL_BITS_(\w+)\s+(\d+)',text,re.M)}
    if offsets.get('AP_CTRL')!=0 or offsets.get('AP_RETURN')!=16:raise ValueError('Unsupported control ABI')
    return {'offsets':offsets,'widths':widths,'header_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def generate(layer,descriptor):
    result={'schema':1,'target_part':'xck26-sfvc784-2LV-c','workspace_bytes':16*1024*1024,
            'layer':parse_header(layer),'descriptor':parse_header(descriptor)}
    for core,names in [('layer',('IMAGE_R','BLURRED','RESIZED','SELECTED','RESULT','STATS')),
                       ('descriptor',('RAW','BLURRED','POINTS','FEATURES','STATS'))]:
        for name in names:
            if result[core]['widths'].get(name+'_DATA')!=64:raise ValueError(f'{core}.{name} is not a 64-bit pointer')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--layer',type=Path,required=True);p.add_argument('--descriptor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(generate(a.layer,a.descriptor),indent=2)+'\n')
