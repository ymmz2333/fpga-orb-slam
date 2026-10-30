"""Independent DTB token parser and exact semantic-diff checks, not a DT generator."""
from pathlib import Path
import argparse
import json
import struct


def parse(path):
    data=path.read_bytes();header=struct.unpack_from('>10I',data)
    magic,size,structure,strings,reserved,version,last,cpu,ns,nstruct=header
    if magic!=0xd00dfeed or size!=len(data) or version<16 or structure+nstruct>size or strings+ns>size:
        raise ValueError('Invalid FDT bounds/header')
    props={};stack=[];pos=structure
    while True:
        token=struct.unpack_from('>I',data,pos)[0];pos+=4
        if token==1:
            end=data.index(0,pos);name=data[pos:end].decode();pos=(end+4)&~3
            stack.append(name);props['/'+'/'.join(stack[1:])]={}
        elif token==2:
            if not stack:raise ValueError('Unbalanced nodes')
            stack.pop()
        elif token==3:
            count,nameoff=struct.unpack_from('>2I',data,pos);pos+=8
            if nameoff>=ns or pos+count>structure+nstruct:raise ValueError('Invalid property bounds')
            end=data.index(0,strings+nameoff);name=data[strings+nameoff:end].decode()
            node=props['/'+'/'.join(stack[1:])]
            if name in node:raise ValueError('Duplicate property')
            node[name]=data[pos:pos+count];pos=(pos+count+3)&~3
        elif token==4:pass
        elif token==9:
            if stack:raise ValueError('Unclosed nodes')
            break
        else:raise ValueError('Invalid token')
    reservations=[]
    while True:
        address,count=struct.unpack_from('>2Q',data,reserved);reserved+=16
        if not address and not count:break
        reservations.append((address,count))
    return props,reservations,cpu


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original',type=Path);parser.add_argument('modified',type=Path)
    a=parser.parse_args();old,ore,cpu=parse(a.original);new,nre,ncpu=parse(a.modified)
    names=['Check_GPIO@43c70000','DVP_Capture2DDR@43c00000','Measure_Camera_Parametar@43c60000',
           'audio_formatter@43c10000','i2c@41600000','dma@43000000','clk_wiz@43c20000',
           'i2s_receiver@43c30000','i2s_transmitter@43c40000','v_tc@43c50000','xlnx_vdma_lcd']
    expected={'/amba_pl/'+name for name in names}
    if '/reserved-driver@1' in old:expected.add('/reserved-driver@1')
    differences=[]
    if ore!=nre or cpu!=ncpu:raise ValueError('Reservation/boot CPU changed')
    if set(new)-set(old)!={'/orb60@43c00000'} or set(old)-set(new):raise ValueError('Unexpected node changes')
    for path,properties in old.items():
        target=dict(properties)
        if path in expected:target['status']=b'disabled\0'
        if new[path]!=target:raise ValueError('Unexpected property change: '+path)
        if new[path]!=properties:differences.append(path+'.status')
    orb=new['/orb60@43c00000']
    wanted=dict(compatible=b'generic-uio\0',status=b'okay\0',
                reg=struct.pack('>6I',0x43c00000,0x10000,0x43c10000,0x10000,0x20000000,0x1000000),
                **{'reg-names':b'layer\0descriptor\0dedicated-ddr\0'})
    if orb!=wanted:raise ValueError('ORB/HDMI shared UIO contract mismatch')
    report=dict(status='PASS',preserved_nodes=len(old),changed_existing_properties=differences,
                new_node='/orb60@43c00000',boot_cpu=cpu,reservation_entries=ore,
                scope='All unlisted properties and nodes byte-identical; kernel/boot validation separate')
    output=a.modified.parent/'semantic_check.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
