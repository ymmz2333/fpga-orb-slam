"""PS/software: exercise actual mono_euroc LoadImages on normalized full inputs."""
import argparse
import json
import pathlib
import subprocess
import sys
from golden_audit_support import write_timestamps,atomic_json,canonical_timestamps,read_rows
from golden_decision_audited import PROJECT,ROOT,EXPERIMENT,sha,cores

def main():
    p=argparse.ArgumentParser();p.add_argument('--previous',required=True,type=pathlib.Path);p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--smoke-only',action='store_true');a=p.parse_args()
    if a.smoke_only:
        state=json.loads((a.output/'state.json').read_text());assert state['status']=='PASSED'
        manifest=json.loads((a.previous/'configs/manifest.json').read_text());d=manifest['datasets'][0]
        ns,_=canonical_timestamps(state['checks'][0]['timestamps'])
        short=a.output/'MH01_first20_timestamps.txt'
        with short.open('xb') as stream:stream.write(''.join(str(t)+'\n' for t in ns[:20]).encode('ascii'))
        binary=PROJECT/'.work/golden/slam_source/Examples/Monocular/mono_euroc';run=a.output/'MH01_smoke20'
        with (a.output/'actual_slam_smoke.log').open('w') as log:
            subprocess.run([sys.executable,str(EXPERIMENT/'scripts/run_pc_slam.py'),'--binary',str(binary),'--vocabulary',str(binary.parents[2]/'Vocabulary/ORBvoc.txt'),
                '--yaml',d['configs']['native'],'--dataset',d['path'],'--timestamps',str(short),'--output',str(run),'--sequence','INPUT_RECOVERY_SMOKE','--candidate','native','--cores',','.join(map(str,cores()[0])),'--wait-lock'],stdout=log,stderr=subprocess.STDOUT,check=True)
        metadata=json.loads((run/'run_metadata.json').read_text());assert metadata['status']=='FINISHED' and metadata['completed_frames']==20
        frames=read_rows(run/'TrackingStates.csv');assert any(r['state_after']=='2' for r in frames)
        atomic_json(a.output/'real_slam_smoke.json',dict(status='PASSED',frames=20,scope='Input regression only; not a B3 repeat or replacement',binary_sha256=sha(binary)))
        print('ACTUAL_SLAM_INPUT_SMOKE_PASS frames=20');return
    a.output.mkdir(exist_ok=False)
    source=PROJECT/'.work/golden/slam_source/Examples/Monocular/mono_euroc.cc'
    text=source.read_text();definition=text[text.rfind('void LoadImages('):]
    if not definition.startswith('void LoadImages(') or not definition.rstrip().endswith('}'):raise ValueError('Unable to isolate actual LoadImages definition')
    probe=a.output/'actual_reader.cc'
    probe.write_text('#include <iostream>\n#include <fstream>\n#include <sstream>\n#include <vector>\n#include <string>\nusing namespace std;\n'+definition+'''
int main(int argc,char**argv) {
  if(argc!=3)return 3; vector<string> names;vector<double> times;
  LoadImages(argv[1],argv[2],names,times);
  for(size_t i=0;i<names.size();++i) { ifstream f(names[i]);if(!f) {cerr<<"INPUT_IMAGE_MISSING index="<<i<<" filename="<<names[i]<<endl;return 2;} }
  cout<<"MONO_ACTUAL_LOADIMAGES_INPUT_PASS frames="<<names.size()<<endl;return 0;
}
''')
    binary=a.output/'actual_reader'
    with (a.output/'build.log').open('w') as log:subprocess.run(['g++','-std=c++14','-O3',str(probe),'-o',str(binary)],stdout=log,stderr=subprocess.STDOUT,check=True)
    manifest=json.loads((a.previous/'configs/manifest.json').read_text());checks=[]
    for d in manifest['datasets']:
        target=a.output/(d['name']+'_timestamps.txt');ns=write_timestamps(d['timestamps'],target)
        result=subprocess.run([str(binary),str(pathlib.Path(d['path'])/'mav0/cam0/data'),str(target)],capture_output=True,text=True)
        (a.output/(d['name']+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Actual mono_euroc reader failed: '+d['name'])
        assert result.stdout.strip()=='MONO_ACTUAL_LOADIMAGES_INPUT_PASS frames='+str(d['full_frames'])
        checks.append(dict(dataset=d['name'],status='PASS',frames=len(ns),timestamps=str(target),sha256=sha(target),source_sha256=sha(pathlib.Path(d['timestamps']))))
    original=manifest['datasets'][0]
    bad=subprocess.run([str(binary),str(pathlib.Path(original['path'])/'mav0/cam0/data'),original['timestamps']],capture_output=True,text=True)
    assert bad.returncode==2 and 'INPUT_IMAGE_MISSING index=0' in bad.stderr
    (a.output/'old_CRLF_reproduction.log').write_text(bad.stdout+bad.stderr)
    atomic_json(a.output/'state.json',dict(status='PASSED',actual_reader_source_sha256=sha(source),checks=checks,old_CRLF_reproduced=True,originals_unchanged=True))
    print('ACTUAL_MONO_INPUT_PASS full_frames='+str(sum(r['frames'] for r in checks))+' old CRLF failure reproduced')
if __name__=='__main__':main()
