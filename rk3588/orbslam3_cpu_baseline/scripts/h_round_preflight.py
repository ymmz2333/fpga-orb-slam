"""Small real-input launch audit: cached T2 == individual, actual codec, geometry."""
import collections,csv,json,os,pathlib,subprocess
from golden_audit_support import atomic_json,packet,read_rows
from run_pc_slam import library_environment
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1];GOLDEN=PROJECT/'orb_frontend_golden'
def main():
    out=GOLDEN/'decision/H1_H2_small_launch_checks_20261006_01';out.mkdir(exist_ok=False)
    old=GOLDEN/'decision/G1_layers_resume_20261006_013559';datasets=json.loads((old/'configs/manifest.json').read_text())['datasets']
    cli=PROJECT/'.work/golden_h2/build/orb_golden_cli';codec=[];counts=0
    sizes=read_rows(GOLDEN/'delivery/v095/pyramid_storage.csv')
    for d in datasets:
        folder=out/d['name'];folder.mkdir();ns=list(map(int,pathlib.Path(d['timestamps']).read_text().split()));chosen=[ns[0],ns[145]]
        stamps=folder/'timestamps.txt';stamps.write_text(''.join(str(t)+'\n' for t in chosen));corpus=folder/'corpus'
        cmd=[str(cli),'--input',str(pathlib.Path(d['input_hashes']).parent),'--sequence',str(stamps),'--output',str(corpus),'--profiles','L8_T2,L4_T2','--stats',str(folder/'stats.csv')]
        with (folder/'sequence.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        for v in ['L8_T2','L4_T2']:
            for role,budget in [(0,1000),(1,5000)]:
                for t in chosen:
                    p=corpus/v/('normal' if not role else 'initialization')/(str(t)+'.orb');single=folder/'individual.orb';levels=int(v[1])
                    cmd=[str(cli),'--input',str(pathlib.Path(d['input_hashes']).parent/(str(t)+'.pgm')),'--output',str(single),'--levels',str(levels),'--features',str(budget),'--timestamp',str(t),'--role',str(role),'--dual-threshold','1']
                    with (folder/'individual.log').open('a') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
                    if single.read_bytes()!=p.read_bytes():raise ValueError('Cached sequence differs from independent extraction')
                    packet(p.read_bytes(),t,role,d['width'],d['height'],levels,budget);counts+=1
                    codec.append('%s\t%d\t%d\t%d\t%d\t%d\t%d\n'%(p,t,role,d['width'],d['height'],levels,budget))
        actual=read_rows(folder/'stats.csv')
        for s in actual:
            ref=next(r for r in sizes if int(r['input_width'])==d['width'] and int(r['input_height'])==d['height'] and r['level']==s['level'])
            if (ref['width'],ref['height'])!=(s['width'],s['height']):raise ValueError('Spec geometry differs from actual model')
        if d['name']!='MH01':
            env=dict(os.environ,LD_LIBRARY_PATH=str(PROJECT/'.work/golden/opencv-install/lib'))
            with (folder/'native.log').open('w') as log:subprocess.run([str(PROJECT/'.work/golden_h2/native_counts/native_selected_counts'),str(pathlib.Path(d['input_hashes']).parent),str(stamps),str(folder/'native.csv')],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            ns0=chosen[0];selected=read_rows(folder/'native.csv');total=sum(int(s['selected']) for s in selected if int(s['timestamp_ns'])==ns0 and s['role']=='1')
            used=read_rows(old/'runs'/(d['name']+'__native__run01')/'FeatureTimeStats.csv')[0]
            if used['role']!='1' or total!=int(used['count']):raise ValueError('Native counter does not match actual historical used total')
    index=out/'codec.tsv';index.write_text(''.join(codec));env,prefix=library_environment(PROJECT/'.work/golden_h1/fixed_v1/slam_source/Examples/Monocular/mono_euroc')
    with (out/'codec.log').open('w') as log:subprocess.run([str(GOLDEN/'decision/G1_audit_20261005_02/packet_probe/golden_packet_probe'),str(index),str(out/'roundtrip.orb')],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    if (out/'codec.log').read_text().strip()!='B1_ACTUAL_CODEC_BYTE_EXACT packets='+str(counts):raise ValueError('Actual codec failed')
    atomic_json(out/'acceptance.json',dict(status='PASSED',cached_vs_individual_packets=counts,actual_codec_packets=counts,geometry='v0.95 dimensions equal real model at both resolutions',native_counter='both Tello first-frame actual used total matches G1 archive'))
    print('H_ROUND_SMALL_PREFLIGHT_PASS packets='+str(counts))
if __name__=='__main__':main()
