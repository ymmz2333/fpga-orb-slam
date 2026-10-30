"""Independent exhaustive address proof for the root-separated heap build."""
import argparse
import json
from pathlib import Path


def proof():
    nodes=list(range(255,1,-1));writes={node:i for i,node in enumerate(nodes)}
    raw=[];war=[];waw=[];intra=[]
    # Compare actual physicalbank/address pairs, not just logical heap indices.
    address=lambda value:(value%2,value//2)
    for i,node in enumerate(nodes):
        for child in (2*node,2*node+1):
            for j,other in enumerate(nodes):
                if address(child)!=address(other):continue
                if j<i:raw.append(dict(writer=other,reader=node,child=child,distance=i-j))
                if j>i:war.append((node,other))
                if j==i:intra.append((node,other))
        for other in nodes[i+1:]:
            if address(node)==address(other):waw.append((node,other))
    assert raw and min(r['distance'] for r in raw)==2
    assert not war and not waw and not intra
    assert writes[2]==len(nodes)-1 and writes[3]==len(nodes)-2
    return dict(status='PASS',build_nodes=len(nodes),raw_dependencies=len(raw),minimum_true_raw_distance=2,
        physical_bank_count=2,war_count=0,waw_count=0,intra_raw_count=0,root_reads_after_build_drain=[2,3],
        raw=raw,scope='Exhaustive address/dependency proof only; actual HLS II/C-RTL/protocol/fullroute remain separate gates')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=proof()
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('TOURNAMENT_TRUE_DEPENDENCY_PROOF_PASS minimumRAWdistance=2 root=separate no_removed_dependencies')


if __name__=='__main__':main()
