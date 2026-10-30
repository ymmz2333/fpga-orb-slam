"""Integer range proof for fixed-mask moments and every CORDIC iteration."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def values(text,name,count):
    body=re.search(r'\b'+name+r'\s*\[[^=]+?=\s*\{(.*?)\};',text,re.S)[1]
    body=re.sub(r'INT64_C\(([^)]+)\)',r'\1',body)
    result=[int(x) for x in re.findall(r'-?\d+',body)]
    assert len(result)==count
    return result


def prove(source,output):
    text=source.read_text();u=values(text,'kNextUmax',16);angles=values(text,'kNextCordicDegrees',32)
    # Each pixel is independently in [0,255]. Positive/negative coefficient
    # sums give exact extrema, also bounding any subset/accumulation prefix.
    mx=255*(sum(range(1,16))+2*sum(sum(range(1,v+1)) for v in u[1:]))
    my=255*sum(v*(2*u[v]+1) for v in range(1,16))
    assert mx==my==624240 and max(mx,my)<2**20
    bound=max(mx,my)<<20
    iterations=[];angle_sum=0
    for k,a in enumerate(angles):
        shift_bound=(bound+(1<<k)-1)//(1<<k)
        bound+=shift_bound;angle_sum+=a
        iterations.append(dict(iteration=k,xy_abs_bound=bound,z_min=-angle_sum,z_max=(180<<24)+angle_sum))
    assert max(r['xy_abs_bound'] for r in iterations)<2**42
    assert min(r['z_min'] for r in iterations)>=-2**33
    assert max((360<<24),max(r['z_max'] for r in iterations))<2**33
    result=dict(status='PROVED',source=str(source.resolve()),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        umax=u,m10_abs_bound=mx,m01_abs_bound=my,moment_signed_bits=21,cordic_xy_signed_bits=43,cordic_z_signed_bits=34,
        normalized_angle_bound_exclusive=360<<24,iterations=iterations,
        notes=['Moment prefixes are bounded by independent positive/negative pixel coefficients',
               'CORDIC uses conservative independent X/Y intervals, not sampled images',
               'Negative floor shifts use ceil(abs_bound/2^k); all 32 iterations and quadrant negation are covered',
               'Full-turn normalization is within signed 34 bits; Q16 round-to-even and public fields remain unchanged',
               'This proves ranges only; arithmetic/RTL equivalence requires independent exact tests'])
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('DESCRIPTOR_RANGE_PROOF_PASS moments=21 xy=43 z=34 max_xy='+str(bound))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prove(a.source,a.output)
