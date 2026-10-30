"""Revalidate retained preflight evidence; run only the three missing G1 smokes.

The previous FAILED record remains immutable. Candidate failures remain failures;
protocol, binary, watchdog and data-integrity gates must still pass.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
from golden_audit_support import atomic_json, packet, binding, classify, read_rows
from golden_linkage_check import pc_baseline
from run_pc_slam import library_environment, verify_linkage

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = EXPERIMENT.parents[1]
GOLDEN = PROJECT / 'orb_frontend_golden'
sys.path.insert(0, str(GOLDEN / 'scripts'))
from common import DATASETS, sha, stamps
from b3_decision import cores


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--previous', type=pathlib.Path, required=True)
    p.add_argument('--output', type=pathlib.Path, required=True)
    a = p.parse_args()
    old, out = a.previous.resolve(), a.output.resolve()
    out.mkdir(exist_ok=False)
    state = dict(status='RUNNING', phase='revalidate_evidence', previous=str(old),
                 previous_state_sha256=sha(old / 'state.json'), checks=[], candidate_outcomes=[])
    def save(): atomic_json(out / 'state.json', state)
    def call(name, cmd, environment=None, allow_failure=False):
        state['phase'] = name; save(); print('AUDIT', name, flush=True)
        with (out / (name + '.log')).open('w') as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=environment)
        if result.returncode and not allow_failure: raise RuntimeError(name + ' failed: see bounded log')
        return result.returncode
    save()
    try:
        previous = json.loads((old / 'state.json').read_text())
        coord = old.with_name(old.name.removesuffix('_preflight') + '_coordinator')
        frozen = json.loads((coord / 'state.json').read_text())['source_sha256']
        for relative, digest in frozen.items():
            if relative.startswith('orb_frontend_golden\\'):
                assert sha(PROJECT / relative.replace('\\', '/')) == digest, relative
        source = PROJECT / '.work/golden/slam_source'
        binary = source / 'Examples/Monocular/mono_euroc'
        assert sha(binary) == previous['binary_sha256']
        for path in (EXPERIMENT / 'vendor/ORB_SLAM3').rglob('*'):
            rel = path.relative_to(EXPERIMENT / 'vendor/ORB_SLAM3')
            if rel.parts[0] not in ('src', 'include') or path.suffix not in ('.cc', '.cpp', '.h', '.hpp'): continue
            assert path.read_text() == (source / rel).read_text(), str(rel)
        original_mono = (EXPERIMENT / 'vendor/ORB_SLAM3/Examples/Monocular/mono_euroc.cc').read_text()
        actual_mono = (source / 'Examples/Monocular/mono_euroc.cc').read_text()
        for line in ['    // Headers and completed-frame rows must survive a watchdog termination.\n',
                     '    featureFile.flush();\n', '    mapFile.flush();\n', '    stateFile.flush();\n',
                     '            // Flush after t2: logging does not change TrackMonocular or realtime pacing.\n',
                     '            featureFile.flush();\n', '            mapFile.flush();\n', '            stateFile.flush();\n']:
            assert line in actual_mono; actual_mono = actual_mono.replace(line, '', 1)
        assert actual_mono == original_mono
        env, library = library_environment(binary)
        (out / 'linkage.ldd.txt').write_text(verify_linkage(binary, env, library))
        pc_baseline()  # Original regression binary still matches PC0 manifest.
        fixture = old / 'watchdog_fixture'
        fm = json.loads((fixture / 'run_metadata.json').read_text())
        assert fm['stack_capture_ok'] and fm['task_status_files'] >= 3 and fm['completed_frames'] == 3
        assert 'NO_FRAME_PROGRESS_120S' in fm['failure_reason']
        assert '#0' in (fixture / 'hang_snapshot/threads.gdb.txt').read_text()
        assert all(len(read_rows(fixture / f)) == 3 for f in ('TrackingStates.csv','MapStateStats.csv','FeatureTimeStats.csv'))
        for name in ['MH01_native_unflushed600'] + ['MH01_native_flushed600_%02d' % n for n in (1,2,3)]:
            m = json.loads((old / name / 'run_metadata.json').read_text())
            rr = read_rows(old / name / 'TrackingStates.csv')
            assert m['status'] == 'FINISHED' and len(rr) == 600 and next(i for i,r in enumerate(rr) if r['state_after']=='2') == 2
            assert all(r['state_after']=='2' for r in rr[2:])
        oracle = previous['frame_oracle']
        assert sha(oracle['binary']) == oracle['sha256']
        manifest = []; smokes = []
        for index, d in enumerate(DATASETS):
            width,height = (752,480) if index==0 else (960,720)
            short = old / d['name']; ns_list = stamps(d)[:150]
            assert list(map(int,(short/'timestamps_150.txt').read_text().split())) == ns_list
            expected_yaml = (EXPERIMENT / ('configs/a3/baseline_752x480.yaml' if index==0 else 'configs/c/tello_oafd_960x720_provisional.yaml')).read_text()
            assert (short/'native.yaml').read_text() == expected_yaml
            for r in json.loads((short/'input_hashes.json').read_text()):
                assert sha(d['path']/'mav0/cam0/data'/(str(r['timestamp_ns'])+'.png')) == r['source_sha256']
                assert sha(short/'pgm'/(str(r['timestamp_ns'])+'.pgm')) == r['pgm_sha256']
            if index:
                native = short/'native_packets'
                for ns in ns_list:
                    for role in ('normal','initialization'):
                        b = (native/role/(str(ns)+'.orb')).read_bytes()
                        assert b == (short/'standalone_corrected'/role/(str(ns)+'.orb')).read_bytes()
                        assert b[64:] == (native/'memory'/role/(str(ns)+'.bin')).read_bytes()
                rr = []
                for mode in ('native_dump150','native_replay150'):
                    folder = old/(d['name']+'_'+mode)
                    assert json.loads((folder/'run_metadata.json').read_text())['status']=='FINISHED'
                    records = read_rows(folder/'FeatureTimeStats.csv'); assert len(records)==150
                    for i,r in enumerate(records):
                        assert int(r['timestamp_ns'])==ns_list[i] and int(r['role']) in (0,1)
                        assert int(r['extractor_calls']) == (2 if mode=='native_dump150' else 0)
                        role=int(r['role']); path=native/('initialization' if role else 'normal')/(str(ns_list[i])+'.orb')
                        assert int(r['count'])==packet(path.read_bytes(),ns_list[i],role,width,height,8,5000 if role else 1000)
                    rr.append([(r['timestamp_ns'],r['role']) for r in records])
                assert rr[0]==rr[1]
            for variant in ('V0','L8','L4','L2','L1'):
                levels = 8 if variant=='V0' else int(variant[1:])
                yaml_text=re.sub(r'(?m)^(ORBextractor.nLevels:)\s*[^\n]+',r'\g<1> '+str(levels),expected_yaml)
                yaml=short/(variant+'.yaml')
                if yaml.exists():assert yaml.read_text()==yaml_text
                else:
                    yaml=out/(d['name']+'_'+variant+'.yaml');yaml.write_text(yaml_text)
                corpus=short/'g1'/variant
                for ns in ns_list:
                    for role,role_name in ((0,'normal'),(1,'initialization')):
                        path=corpus/role_name/(str(ns)+'.orb')
                        packet(path.read_bytes(),ns,role,width,height,levels,5000 if role else 1000)
                        manifest.append('%s\t%d\t%d\t%d\t%d\t%d\t%d\n'%(path,ns,role,width,height,levels,5000 if role else 1000))
                name=d['name']+'_'+variant+'_inject150'
                smokes.append((d,variant,levels,width,height,ns_list,short,corpus,name,yaml))
        (out/'packets.tsv').write_text(''.join(manifest))
        build=out/'packet_probe'
        call('codec_configure',['cmake','-S',str(EXPERIMENT/'tools/golden_packet_probe'),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_FLAGS=-march=native -fPIC','-DORB_SOURCE='+str(source),'-DOpenCV_DIR='+str(library/'cmake/opencv4')])
        call('codec_build',['cmake','--build',str(build),'-j','2'])
        call('actual_B1_roundtrip',[str(build/'golden_packet_probe'),str(out/'packets.tsv'),str(out/'roundtrip.orb')],env)
        state['checks'].append(dict(name='all_short_packets_actual_B1_codec',status='PASS',packets=len(manifest)))
        cpu=','.join(map(str,cores()[0]))
        for d,v,levels,w,h,ns_list,short,corpus,name,yaml in smokes:
            folder=old/name
            if not (folder/'run_metadata.json').exists():
                folder=out/name
                call(name,[sys.executable,str(EXPERIMENT/'scripts/run_pc_slam.py'),'--binary',str(binary),'--vocabulary',str(source/'Vocabulary/ORBvoc.txt'),'--yaml',str(yaml),'--dataset',str(d['path']),'--timestamps',str(short/'timestamps_150.txt'),'--output',str(folder),'--sequence',d['name'],'--candidate',v,'--cores',cpu,'--feature-mode','inject','--feature-directory',str(corpus),'--wait-lock'],allow_failure=True)
            metadata=json.loads((folder/'run_metadata.json').read_text())
            count=binding(folder,ns_list,corpus,levels,w,h)
            assert count==metadata['completed_frames']
            outcome=classify(metadata,folder)
            state['candidate_outcomes'].append(dict(dataset=d['name'],variant=v,status=metadata['status'],classification=outcome,frames=count,expected=150,raw=str(folder)))
            save()
        assert sha(binary)==previous['binary_sha256']
        state.update(status='PASSED',phase='audit_complete',binary_sha256=sha(binary),
                     candidate_failures=sum(r['status']!='FINISHED' for r in state['candidate_outcomes']),
                     interpretation='Infrastructure gates passed; candidate failures retained, never relabeled as successful runs')
        save(); print('G1_AUDIT_PASS candidate_failures='+str(state['candidate_failures']),flush=True); return 0
    except Exception as e:
        state.update(status='FAILED',error=str(e));save();raise

if __name__=='__main__': raise SystemExit(main())
