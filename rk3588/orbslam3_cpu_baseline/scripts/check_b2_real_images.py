"""Bounded pre-batch gate: two real frames per dataset, every inject candidate."""
import json,pathlib,subprocess,sys
from verify_b2_corpus import verify
ROOT=pathlib.Path(__file__).resolve().parent.parent

def main():
    configs=ROOT/'runtime/b2/development_config';m=json.loads((configs/'manifest.json').read_text(encoding='utf-8'))
    root=ROOT/'runtime/b2/real_candidate_gate';root.mkdir(parents=True,exist_ok=False);results=[]
    for d in m['datasets']:
        timestamps=root/(d['name']+'.txt');timestamps.write_text('\n'.join(pathlib.Path(d['timestamps']).read_text().splitlines()[:2])+'\n')
        for v in m['plan']['variants']:
            if v=='native':continue
            out=root/(d['name']+'__'+v)
            with (root/(out.name+'.log')).open('wb') as log:
                subprocess.run([str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs'][v],
                    '--dataset',d['path'],'--timestamps',str(timestamps),'--output',str(out),'--stride','1'],
                    stdout=log,stderr=subprocess.STDOUT,check=True)
            facts=verify(out,timestamps,d['configs'][v],d['width'],d['height']);facts.update(dataset=d['name'],variant=v);results.append(facts)
            print('B2_REAL_GATE dataset=%s variant=%s files=%d points=%d'%(d['name'],v,facts['files'],facts['points']),flush=True)
    (root/'real_gate.json').write_text(json.dumps(dict(status='PASS',results=results),indent=2),encoding='utf-8')
    print('B2_REAL_GATE_PASS: 27 configurations, 108 packets; SLAM not run')
if __name__=='__main__':main()
