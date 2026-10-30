"""Freeze the exact accepted control-register ABI for the Linux driver."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pair',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    pair=args.pair.resolve()
    state=json.loads((pair/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['PeriodNs'] < 6.667
    args.output.mkdir(parents=True,exist_ok=True)
    declarations=['/* Generated from the paired, accepted Vitis HLS register headers. */']
    manifest={}
    for prefix,key,kernel in [('L','LayerHlsJob','layer2'),('D','DescriptorHlsJob','descriptor')]:
        job=Path(state[key])
        accepted=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
        assert accepted['State']=='SUCCEEDED' and accepted['Cosim'] and accepted['Part']=='xc7z015clg485-2'
        top=f'fastv2_{kernel}_hls'
        header=job/f'projects/{kernel}/solution1/impl/ip/drivers/{top}_v1_0/src/x{top}_hw.h'
        text=header.read_text()
        assert all(int(width)==32 for width in re.findall(r'_CONTROL_BITS_\w+_DATA\s+(\d+)',text))
        for key,value in re.findall(r'_CONTROL_ADDR_(\w+)\s+(0x[0-9a-fA-F]+)',text):
            declarations.append(f'#define {prefix}_{key.removesuffix("_DATA")} {value}u')
        dest=args.output/header.name
        shutil.copyfile(header,dest)
        manifest[prefix]={'job':str(job),'header_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
    bit=pair/'bit/orb60_150mhz.bit'
    digest=hashlib.sha256(bit.read_bytes()).hexdigest()
    assert digest=='b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60'
    manifest.update(bit=str(bit),bit_sha256=digest,device='xc7z015clg485-2',ps_fclk_hz=100000000,pl_hz=150000000,
                    feature_capacity=1000,geometry=[960,720,8],scope='Linux bringup inputs, board acceptance pending')
    (args.output/'orb60_registers.h').write_text('\n'.join(declarations)+'\n',encoding='utf-8')
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copyfile(bit,args.output/bit.name)
    (args.output/'bitstream.bif').write_text('all:\n{\n orb60_150mhz.bit\n}\n',encoding='ascii')
    print('LINUX_REGISTER_ABI_AND_BIT_HASH_PASS')


if __name__=='__main__':
    main()
