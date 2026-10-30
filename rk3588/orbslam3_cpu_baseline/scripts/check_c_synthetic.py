"""Verify C1 diagnostics on A1's 24 synthetic frames; not a C2 experiment."""
import json,os,pathlib,subprocess,time
from analyze_c import analyze_run,read
ROOT=pathlib.Path(__file__).resolve().parents[1]
output=ROOT/'runtime/c'/('synthetic_'+time.strftime('%Y%m%dT%H%M%S')+'_'+str(os.getpid())); output.mkdir(parents=True)
subprocess.run(['python3',str(ROOT/'scripts/make_smoke_sequence.py')],check=True)
data=ROOT/'runtime/smoke_input'; source=ROOT/'vendor/ORB_SLAM3'
env=os.environ.copy(); env.pop('DISPLAY',None); env['LD_LIBRARY_PATH']=str(ROOT/'install/lib')
cmd=[str(source/'Examples/Monocular/mono_euroc'),str(source/'Vocabulary/ORBvoc.txt'),str(data/'smoke.yaml'),str(data),str(data/'timestamps.txt'),'synthetic','--no-viewer','--feature-mode','native']
with (output/'program.log').open('wb') as log: subprocess.run(cmd,cwd=str(output),env=env,stdout=log,stderr=log,check=True,timeout=120)
facts=analyze_run(output,24)
assert len(read(output/'MapStateStats.csv'))==24
assert not facts['initialization_succeeded']
result=dict(status='PASS',frames=24,synthetic_only=True,map_state_rows=24,final_map_rows=facts['maps'],algorithm_accuracy_or_timing_baseline=False,output=str(output))
(output/'acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('C1_SYNTHETIC_PASS '+json.dumps(result))
