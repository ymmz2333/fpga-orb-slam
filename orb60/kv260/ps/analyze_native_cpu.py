"""Resolve native sampled PCs using captured ELF segments and exact symbol files."""
import argparse
from bisect import bisect_right
from collections import Counter,defaultdict
import json
from pathlib import Path
import re


def parse_maps(text):
    result=[]
    for line in text.splitlines():
        p=line.split(None,5)
        if len(p)!=6 or 'x' not in p[1] or not p[5].startswith('/'):continue
        lo,hi=(int(x,16) for x in p[0].split('-'))
        if lo>=hi:raise ValueError('Invalid executable mapping')
        result.append(dict(start=lo,end=hi,offset=int(p[2],16),path=p[5]))
    if not result:raise ValueError('No executable mappings')
    return sorted(result,key=lambda x:x['start'])


def elf_address(ip,mapping,layout):
    if not mapping['start']<=ip<mapping['end']:raise ValueError('PC outside mapping')
    file_offset=mapping['offset']+ip-mapping['start']
    found=[s for s in layout['segments'] if s['flags']&1 and s['offset']<=file_offset<s['offset']+s['filesz']]
    if len(found)!=1:raise ValueError('PC not in one captured executable ELF segment')
    s=found[0]
    return s['vaddr']+file_offset-s['offset']


def symbols(text):
    entries={}
    rank={'T':0,'t':1,'W':2,'w':3}
    for line in text.splitlines():
        m=re.fullmatch(r'([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([TtWw])\s+(.+)',line)
        if not m:continue
        start,size,kind,name=int(m[1],16),int(m[2],16),m[3],m[4]
        if not size:continue
        row=(start,size,name,rank[kind])
        if start not in entries or (rank[kind],len(name),name)<(entries[start][3],len(entries[start][2]),entries[start][2]):entries[start]=row
    return sorted(entries.values())


class Resolver:
    def __init__(self,maps,index,load):
        self.maps=parse_maps(maps);self.starts=[m['start'] for m in self.maps];self.index=index;self.syms={}
        for name,item in index.items():
            rows=symbols('\n'.join(load(p) for p in item['symbol_files']))
            self.syms[name]=([r[0] for r in rows],rows)
    def resolve(self,ip):
        i=bisect_right(self.starts,ip)-1
        if i<0 or not self.maps[i]['start']<=ip<self.maps[i]['end']:return ('[unmapped]','[unmapped]')
        mapping=self.maps[i];module=mapping['path'];item=self.index.get(module)
        if not item:return (module,'[missing captured ELF]')
        try:address=elf_address(ip,mapping,item['layout'])
        except ValueError:return (module,'[unresolved ELF offset]')
        starts,rows=self.syms[module];n=bisect_right(starts,address)-1
        if n<0 or not rows[n][0]<=address<rows[n][0]+rows[n][1]:return (module,'[no function symbol]')
        return (module,rows[n][2])


def run(profile,output):
    profile,output=Path(profile).resolve(),Path(output).resolve()
    proof=json.loads((profile/'PROFILE.json').read_text());sample=json.loads((profile/'SAMPLER.json').read_text())
    if proof['status']!='CPU_DIAGNOSTIC_CAPTURED' or sample['status']!='NATIVE_CPU_SAMPLES_RECORDED' or sample['lost']:
        raise ValueError('Verified actual-DPU CPU diagnostic required')
    resolver=Resolver((profile/'maps.txt').read_text(),json.loads((profile/'ELF_INDEX.json').read_text()),lambda p:(profile/p).read_text())
    leaf=defaultdict(Counter);inclusive=defaultdict(Counter);counts=Counter();depths=Counter()
    for line in (profile/'samples.jsonl').read_text().splitlines():
        r=json.loads(line)
        if r['type']=='lost':raise ValueError('Lost CPU samples')
        if r['type']!='sample':continue
        if r['pid']!=sample['pid']:raise ValueError('Different target sampled')
        tid=r['tid'];counts[tid]+=1;leaf[tid][resolver.resolve(int(r['ip'],16))]+=1
        stack={resolver.resolve(int(x,16)) for x in [r['ip'],*r['callchain']] if int(x,16)<(1<<64)-4095}
        depths[len(stack)]+=1
        for name in stack:inclusive[tid][name]+=1
    if sum(counts.values())!=sample['samples']:raise ValueError('Captured sample count mismatch')
    def top(counter,total):
        return [dict(module=module,function=name,samples=n,fraction=n/total) for (module,name),n in counter.most_common(30)]
    result=dict(status='ACTUAL_NATIVE_CPU_DIAGNOSTIC_ANALYZED',scope='On-CPU samples only from initial native tasks. Inclusive stack counts overlap. No latency or FPS acceptance.',
                pid=sample['pid'],samples=sample['samples'],stack_unique_depth_histogram=dict(depths),threads={})
    for tid,total in counts.most_common():
        result['threads'][str(tid)]=dict(main=tid==sample['pid'],samples=total,leaf=top(leaf[tid],total),inclusive=top(inclusive[tid],total))
    if output.exists():raise ValueError('Fresh diagnostic analysis required')
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],samples=sample['samples'],threads=len(counts))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
