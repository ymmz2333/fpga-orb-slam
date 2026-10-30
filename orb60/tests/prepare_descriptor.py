"""Independent full-table Python direction/BRIEF, never imports DUT offset ROM."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from oracle import WIDTHS, HEIGHTS


def constants(path):
    source=path.read_text()
    def array(name,count):
        body=re.search(r'\b'+name+r'\s*\[[^=]+?=\s*\{(.*?)\};',source,re.S).group(1)
        result=list(map(int,re.findall(r'-?\d+',body)))
        assert len(result)==count,(name,len(result))
        return result
    return array('pattern',1024),array('umax',16),array('trig32',64),array('cordic_degrees_q24',32)


def even(value,denominator):
    q,r=divmod(abs(value),denominator)
    q+=r*2>denominator or (r*2==denominator and q&1)
    return -q if value<0 else q


def angle(m10,m01,cordic):
    if not m01:return 180*65536 if m10<0 else 0
    if not m10:return 270*65536 if m01<0 else 90*65536
    x,y,z=m10*(1<<20),m01*(1<<20),0
    if x<0:x,y,z=-x,-y,180<<24
    for k in range(32):
        if not y:break
        old=x
        if y>0:x,y,z=x+(y>>k),y-(old>>k),z+cordic[k]
        else:x,y,z=x-(y>>k),y+(old>>k),z-cordic[k]
    return even(z%(360<<24),256)%(360<<16)


def describe(raw,blur,width,height,points,level,tables):
    pattern,umax,trig,cordic=tables
    output=[];bins=set()
    for x,y,score,tile in points:
        if not 0<=x<width-32 or not 0<=y<height-32:return -2,output,bins
        cx,cy=x+16,y+16
        m10=sum(u*raw[cy*width+cx+u] for u in range(-15,16));m01=0
        for v in range(1,16):
            vertical=0
            for u in range(-umax[v],umax[v]+1):
                plus=raw[(cy+v)*width+cx+u];minus=raw[(cy-v)*width+cx+u]
                vertical+=plus-minus;m10+=u*(plus+minus)
            m01+=v*vertical
        precise=angle(m10,m01,cordic)
        direction=((precise*32+(360<<15))//(360<<16))%32
        bits=[0]*8;cosine,sine=trig[direction*2:direction*2+2]
        for bit in range(256):
            coords=[]
            for sample in range(2):
                px,py=pattern[bit*4+sample*2:bit*4+sample*2+2]
                ax=cx+even(px*cosine-py*sine,1<<30)
                ay=cy+even(px*sine+py*cosine,1<<30)
                if not 0<=ax<width or not 0<=ay<height:return -2,output,bins
                coords.append(blur[ay*width+ax])
            if coords[0]<coords[1]:bits[bit>>5]|=1<<(bit&31)
        output.append(struct.pack('<7iI8I',cx,cy,score,level,direction,m10,m01,direction*737280,*bits))
        bins.add(direction)
    return 0,output,bins


def bytes_read(width,height,points):
    raw=blur=0
    for x,y,score,tile in points:
        if not 0<=x<width-32 or not 0<=y<height-32:continue
        for row in range(31):
            address=(y+1+row)*width+x+1
            raw+=((address%8+31+7)//8)*8
        cx,cy=x+16,y+16;start=max(0,cx-18);last=min(width-1,cx+18)
        for gy in range(max(0,cy-18),min(height,cy+19)):
            address=gy*width+start
            blur+=((address%8+last-start+1+7)//8)*8
    return raw,blur


def prepare(images,constant_path,output):
    output.mkdir(parents=True,exist_ok=False)
    tables=constants(constant_path);source=json.loads((images/'vectors.json').read_text())
    for name,digest in source['sha256'].items():
        if hashlib.sha256((images/name).read_bytes()).hexdigest()!=digest:raise ValueError('Input vector hash changed')
    cases=[];controls=[];all_bins=set();features=bytearray(b'\xc3'*64000)
    def emit(raw,blur,points,width,height,count,level,offset,capacity,reset,label):
        nonlocal features
        index=len(cases);name=f'd{index:02}'
        if reset:features=bytearray(b'\xc3'*64000)
        valid=33<=width<=960 and 33<=height<=720 and 0<=count<=256 and 0<=level<8 and 0<=offset<=capacity<=1000 and count<=capacity-offset
        raw_bytes=blur_bytes=0
        if valid:
            status,records,bins=describe(raw,blur,width,height,points[:count],level,tables)
            all_bins.update(bins);raw_bytes,blur_bytes=bytes_read(width,height,points[:count])
            for i,record in enumerate(records):features[(offset+i)*64:(offset+i+1)*64]=record
        else:status,records=-1,[]
        packed=bytearray(b'\xa5'*4096)
        for i,point in enumerate(points[:256]):packed[i*16:(i+1)*16]=struct.pack('<4i',*point)
        for suffix,data in dict(raw=raw,blur=blur,points=packed,features=features).items():
            (output/f'{name}_{suffix}.bin').write_bytes(data)
        controls.extend((width,height,count,level,offset,capacity,status,len(records),raw_bytes,blur_bytes,int(reset),0))
        cases.append(dict(index=index,name=name,label=label,count=count,completed=len(records),status=status,level=level,
                          offset=offset,raw_read_bytes=raw_bytes,blur_read_bytes=blur_bytes))
    offsets=[0,0,0]
    for source_case in source['cases']:
        frame,level=source_case['frame'],source_case['level'];prefix=source_case['name']
        raw=(images/f'{prefix}_input.bin').read_bytes();blur=(images/f'{prefix}_blur.bin').read_bytes()
        point_data=(images/f'{prefix}_points.bin').read_bytes()
        points=[struct.unpack_from('<4i',point_data,i*16) for i in range(source_case['selected'])]
        emit(raw,blur,points,WIDTHS[level],HEIGHTS[level],len(points),level,offsets[frame],1000,level==0,source_case['label'])
        offsets[frame]+=len(points)
    # Guards, empty input, invalid controls and failure after an already emitted record.
    zero=(images/'f2_l0_input.bin').read_bytes();zero_blur=(images/'f2_l0_blur.bin').read_bytes()
    emit(zero,zero_blur,[(0,0,0,0),(927,0,255,1),(0,687,1,2),(927,687,254,3)],960,720,4,0,995,1000,True,'legal_extreme_points')
    emit(zero,zero_blur,[(0,0,7,1),(-1,0,8,2),(1,1,9,3)],960,720,3,0,7,1000,True,'invalid_middle_point')
    for label,point in [('bad_x_negative',(-1,0,0,0)),('bad_x_end',(928,0,0,0)),
                        ('bad_y_negative',(0,-1,0,0)),('bad_y_end',(0,688,0,0))]:
        emit(zero,zero_blur,[point],960,720,1,0,0,1000,True,label)
    for width,height,count,level,offset,capacity,label in [
        (960,720,1,0,1000,1000,'append_full'),(960,720,257,0,0,1000,'count_overflow'),
        (960,720,-1,0,0,1000,'negative_count'),(960,720,1,8,0,1000,'bad_level'),
        (32,720,1,0,0,1000,'bad_width'),(960,720,0,0,1000,1000,'empty_at_capacity')]:
        emit(zero,zero_blur,[(0,0,0,0)],width,height,count,level,offset,capacity,True,label)
    pressure=(images/'f1_l0_input.bin').read_bytes();pressure_blur=(images/'f1_l0_blur.bin').read_bytes()
    emit(pressure,pressure_blur,[(0,0,99,0)],960,720,1,0,0,1000,True,'rotated_sample_at_edge')
    odd_raw=(images/'f1_l4_input.bin').read_bytes();odd_blur=(images/'f1_l4_blur.bin').read_bytes()
    points=[(8+(i*37)%415,8+(i*53)%299,(i*19)&255,i%204) for i in range(256)]
    emit(odd_raw,odd_blur,points,463,347,256,4,744,1000,True,'max_call_exact_capacity')
    assert offsets==[280,942,0],offsets
    assert len(all_bins)==32,all_bins
    (output/'cases.bin').write_bytes(struct.pack('<4I',0x60d20001,1,len(cases),1000)+struct.pack('<'+'i'*len(controls),*controls))
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.bin')}
    result=dict(scope='Independent Python original full-32 table arithmetic, true real/noise pyramids',
                constants_sha256=hashlib.sha256(constant_path.read_bytes()).hexdigest(),cases=cases,sha256=hashes,
                bins=sorted(all_bins),frame_counts=offsets,source_vectors=str(images))
    (output/'vectors.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'ORB60_DESCRIPTOR_PYTHON_READY cases={len(cases)} bins={len(all_bins)} frame_counts={offsets}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--images',type=Path,required=True);p.add_argument('--constants',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prepare(a.images,a.constants,a.output)
