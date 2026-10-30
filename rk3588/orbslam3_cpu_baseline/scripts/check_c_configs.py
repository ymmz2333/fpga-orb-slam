"""Diagnostic startup on two real prepared frames for each C YAML; no experiment metrics."""
import argparse,csv,json,os,pathlib,subprocess,time
from analyze_c import analyze_run
from validate_prepared import validate
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(); p.add_argument('--datasets',type=pathlib.Path,required=True); a=p.parse_args()
    corpus=a.datasets.expanduser().resolve()
    first=json.loads((corpus/'manifest.json').read_text(encoding='utf-8'))['clips'][0]
    dataset=corpus/first['dataset']; validate(dataset)
    stamps=(dataset/'timestamps.txt').read_text().splitlines()[:2]
    if len(stamps)!=2: raise ValueError('Need two actual frames')
    base=ROOT/'runtime/c'/('config_smoke_'+str(time.monotonic_ns())); base.mkdir()
    stamp_file=base/'timestamps.txt'; stamp_file.write_text('\n'.join(stamps)+'\n')
    source=ROOT/'vendor/ORB_SLAM3'; env=os.environ.copy(); env.pop('DISPLAY',None)
    env['LD_LIBRARY_PATH']=str(ROOT/'install/lib')
    results=[]
    for yaml in sorted((ROOT/'configs/c').glob('*provisional.yaml')):
        output=base/yaml.stem; output.mkdir()
        command=[str(source/'Examples/Monocular/mono_euroc'),str(source/'Vocabulary/ORBvoc.txt'),
            str(yaml),str(dataset),str(stamp_file),'config_check','--no-viewer','--feature-mode','native']
        with (output/'program.log').open('wb') as f:
            subprocess.run(command,cwd=str(output),env=env,stdout=f,stderr=f,check=True,timeout=120)
        facts=analyze_run(output,2)
        results.append(dict(yaml=yaml.name,frames=facts['processed_frames'],status='PASS'))
    if len(results)!=3: raise ValueError('Expected baseline and two sensitivity YAMLs')
    report=dict(status='PASS',diagnostic_only=True,experiment_metrics=False,results=results,output=str(base))
    (base/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('C_CONFIGS_PASS '+json.dumps(report)); return 0
if __name__=='__main__': raise SystemExit(main())
