"""Group real setup cones without changing path selection or timing checks."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import re


def summarize(root,output=None):
    output=output or root
    output.mkdir(parents=True,exist_ok=True)
    paths=list(csv.DictReader((root/'paths.tsv').open(),delimiter='\t'))
    nets=list(csv.DictReader((root/'nets.tsv').open(),delimiter='\t'))
    assert len(paths)==200 and len({p['endpoint'] for p in paths})==200
    assert len(nets)==50
    report=(root/'setup_200.rpt').read_text()
    sections=re.split(r'(?m)^Slack \(',report)[1:]
    assert len(sections)==200, f'Missing timing report sections: {len(sections)}'
    families={};distribution=Counter()
    for p,section in zip(paths,sections):
        for label,key in [('Source','startpoint'),('Destination','endpoint')]:
            found=re.search(label+r':\s+(\S+)',section)
            assert found and found[1]==p[key],f'Path ordering changed: {label}'
        m=re.search(r'Data Path Delay:\s*([\d.]+)ns\s*\(logic\s+([\d.]+)ns.*?route\s+([\d.]+)ns',section)
        assert m,'Missing logic/routing split'
        total,logic,routing=map(float,m.groups())
        assert abs(total-logic-routing)<0.004
        data=p['startpoint']+' -> '+p['endpoint']
        family=None
        for label,pattern in [('banked_score_update',r'reduce_score_bank'),('grid_selection',r'consume_and_select'),
            ('FAST_score',r'fast_score'),('CORDIC',r'precise_angle'),('orientation_moments',r'(?:moment|Moment)'),
            ('BRIEF',r'(?:brief|Brief)'),('Gaussian_horizontal',r'gaussian2_horizontal'),
            ('Gaussian_vertical',r'gaussian2_vertical'),('Resize',r'resize2_pairs'),('AXI_adapter',r'm_axi')]:
            if re.search(pattern,data):family=label;break
        a=p['startpoint'].split('/')[:-1];b=p['endpoint'].split('/')[:-1];common=[]
        for x,y in zip(a,b):
            if x!=y:break
            common.append(x)
        actor='/'.join(common) or 'cross_hierarchy'
        # Different bits of one destination register share a cone. Keep the
        # actual hierarchy/register so distinct cones within FAST remain visible.
        sink=re.sub(r'\[\d+\]', '',b[-1])
        cone=actor+'/'+sink
        family=family or actor
        levels=int(p['logic_levels']);distribution[levels]+=1
        # Even -path_type full includes clock distribution in this build.
        # Bound the data rows by the actual source/destination pin rows;
        # selecting by clock name or a fanout threshold would mask real nets.
        rows=section.splitlines()
        first=[i for i,line in enumerate(rows) if p['startpoint'] in line.split() and
               not line.lstrip().startswith('Source:')]
        last=[i for i,line in enumerate(rows) if p['endpoint'] in line.split() and
              not line.lstrip().startswith('Destination:')]
        assert len(last)==1, 'Missing or ambiguous destination data pin'
        # Self-feedback has the same launch/capture clock pin twice. Only the
        # launch occurrence precedes the destination data pin; the capture
        # occurrence belongs to the required-time clock section.
        first=[i for i in first if i<last[0]]
        assert len(first)==1, 'Missing or ambiguous launch data boundary'
        data_rows='\n'.join(rows[first[0]+1:last[0]+1])
        fanouts=[int(x) for x in re.findall(r'net \(fo=(\d+),',data_rows)]
        assert fanouts,'Missing data-path fanout evidence'
        p.update(slack_ns=float(p['slack_ns']),logic_levels=levels,logic_ns=logic,routing_ns=routing,
            data_path_fanout_max=max(fanouts),endpoint_kind=p['endpoint'].rsplit('/',1)[-1],
            bram_associated=bool(re.search(r'\bRAMB(?:18|36)',data_rows)),
            dsp_associated=bool(re.search(r'\bDSP48',data_rows)),family=family,cone=cone,
            endpoint_ce=p['endpoint'].rsplit('/',1)[-1].startswith('CE'),
            endpoint_reset=(p['endpoint'].rsplit('/',1)[-1] in {'R','S','CLR','PRE'} or
                            p['endpoint'].rsplit('/',1)[-1].startswith('RST')))
        families.setdefault(cone,[]).append(p)
    hot=[]
    for name,rows in families.items():
        rows.sort(key=lambda x:x['slack_ns'])
        hot.append(dict(family=rows[0]['family'],cone=name,paths=len(rows),worst=rows[0],
                        max_fanout=max(x['data_path_fanout_max'] for x in rows)))
    hot.sort(key=lambda x:x['worst']['slack_ns'])
    for n in nets:
        for key in ['fanout','clock_loads','reset_loads','ce_loads','data_loads']:n[key]=int(n[key])
        assert sum(n[x] for x in ['clock_loads','reset_loads','ce_loads','data_loads'])==n['fanout']
    result=dict(scope='Read-only actual routed DCP diagnostics; no new implementation/board claim',
        input_reports=str(root.resolve()),setup_path_count=200,unique_endpoints=200,logic_levels_distribution=dict(sorted(distribution.items())),
        available_families=len(hot),top_distinct_hotspots=hot[:5],all_hotspots=hot,
        high_fanout_nets=nets,paths=paths,
        notes=['Up to five real families are reported; fewer present in the selected 200 are stated explicitly',
               'Data-path fanout explicitly excludes rows outside actual source/destination pins',
               'Clock/reset/CE/data leaf loads and unavailable data timing are recorded separately'])
    (output/'diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Routed diagnostics','',f'200 unique-endpoint paths; {len(hot)} distinct observed families.','',
           '| Hotspot / destination register | WNS/ns | Logic/ns | Routing/ns | Levels | Data fanout | Endpoint |',
           '|---|---:|---:|---:|---:|---:|---|']
    for group in hot[:5]:
        w=group['worst'];lines.append(f"| {group['family']} / {group['cone'].rsplit('/',1)[-1]} | {w['slack_ns']:.3f} | {w['logic_ns']:.3f} | {w['routing_ns']:.3f} | {w['logic_levels']} | {group['max_fanout']} | {w['endpoint_kind']} |")
    lines+=['',f'Raw timing, fanout load types and detailed control sets: {root.resolve()}']
    (output/'SUMMARY.md').write_text('\n'.join(lines)+'\n')
    print('ROUTED_DIAGNOSTICS_PASS paths=200 nets=50 observed_families='+str(len(hot)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('reports',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();summarize(args.reports,args.output)
