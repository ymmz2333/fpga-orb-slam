"""Validate B1 packets for arbitrary approved candidate levels/resolution."""
import argparse,csv,hashlib,json,math,pathlib,struct
from verify_feature_files import HEADER,RECORD

def verify(corpus,timestamps,config,width,height):
    root=pathlib.Path(corpus);stamps=[int(v) for v in pathlib.Path(timestamps).read_text().splitlines()]
    import re
    text=pathlib.Path(config).read_text(encoding='utf-8')
    def value(key):return float(re.search(r'(?m)^'+re.escape(key)+r':\s*([0-9.]+)',text)[1])
    levels=int(value('ORBextractor.nLevels'));scale=value('ORBextractor.scaleFactor');n=int(value('ORBextractor.nFeatures'));bins=int(value('Design.angle_bins'))
    facts=[]
    for role,name in enumerate(('normal','initialization')):
        if {p.name for p in (root/name).glob('*.orb')}!={str(t)+'.orb' for t in stamps}:raise ValueError('Corpus coverage mismatch')
        for t in stamps:
            path=root/name/(str(t)+'.orb');data=path.read_bytes();h=HEADER.unpack_from(data)
            magic,version,head,record,r,flags,ns,w,ht,count,l,s,features,desc,coords,mono,reserved=h
            if (magic,version,head,record,r,flags,ns,w,ht,l,features,desc,coords,reserved)!=(b'ORBFEAT\0',1,64,64,role,0,t,width,height,levels,n*(5 if role else 1),32,0,0):raise ValueError('B1 header mismatch '+str(path))
            if struct.pack('<f',s)!=struct.pack('<f',scale) or len(data)!=64*(count+1) or not 0<=mono<=count:raise ValueError('Packet shape mismatch')
            populations=[0]*levels
            # Reproduce the float32 scale recurrence used by the native extractor.
            scales=[1.0]
            for level in range(1,levels):scales.append(struct.unpack('<f',struct.pack('<f',scales[-1]*s))[0])
            for x,y,octave,angle,size,response,cls,reserved,desc in RECORD.iter_unpack(data[64:]):
                if not all(math.isfinite(v) for v in (x,y,angle,size,response)) or not (0<=x<width and 0<=y<height and 0<=octave<levels and 0<=angle<360 and reserved==0):raise ValueError('Invalid keypoint')
                if abs(x/scales[octave]-round(x/scales[octave]))>0.001 or abs(y/scales[octave]-round(y/scales[octave]))>0.001:raise ValueError('Noninteger layer coordinate')
                if size!=int(31*scales[octave]) or response!=int(response):raise ValueError('Native size/FAST score mismatch')
                if bins and abs(angle/(360/bins)-round(angle/(360/bins)))>1e-5:raise ValueError('Invalid quantized angle')
                populations[octave]+=1
            memory=root/'memory'/name/(str(t)+'.bin')
            if memory.exists() and memory.read_bytes()!=data[64:]:raise ValueError('In-memory byte mismatch')
            facts.append(dict(timestamp_ns=t,role=role,points=count,levels=populations,sha256=hashlib.sha256(data).hexdigest()))
    with (root/'packet_verification.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(facts[0]));w.writeheader();w.writerows(facts)
    # Independently decoded per-layer populations must agree with generator diagnostics.
    layers=root/'layers.csv'
    if layers.exists():
        with layers.open() as f:rows=list(csv.DictReader(f))
        if len(rows)!=len(facts)*levels:raise ValueError('Layer diagnostic coverage mismatch')
        lookup={(int(r['timestamp_ns']),int(r['role']),int(r['level'])):r for r in rows}
        if len(lookup)!=len(rows):raise ValueError('Duplicate layer diagnostic')
        grid=bool(value('Design.grid'))
        for fact in facts:
            for level,population in enumerate(fact['levels']):
                r=lookup[(fact['timestamp_ns'],fact['role'],level)];selected=int(r['selected']);budget=int(r['budget'])
                if selected!=population or int(r['candidates'])<selected or int(r['shortfall'])!=max(0,budget-selected):raise ValueError('Layer/packet count disagreement')
                if grid and selected>budget:raise ValueError('Grid exceeded layer budget')
    result=dict(status='PASS',files=len(facts),points=sum(r['points'] for r in facts),levels=levels,width=width,height=height)
    (root/'packet_verification.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--corpus',required=True);p.add_argument('--timestamps',required=True);p.add_argument('--config',required=True);p.add_argument('--width',type=int,required=True);p.add_argument('--height',type=int,required=True);a=p.parse_args()
    print('B2_PACKETS '+json.dumps(verify(a.corpus,a.timestamps,a.config,a.width,a.height)))
