"""Synthetic orchestration regression tests; these are NOT B3 measurements."""
import csv
import importlib.util
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
import time
import fcntl
from unittest.mock import patch
from golden_audit_support import packet, CompletedProgress, atomic_json, classify, read_rows,canonical_timestamps,write_timestamps

HERE=pathlib.Path(__file__).resolve().parent
def module(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def sample():
    data=bytearray(128);data[:8]=b'ORBFEAT\0'
    struct.pack_into('<HHHBBQIIII',data,8,1,64,64,0,0,1000000000,752,480,1,8)
    struct.pack_into('<fIIIiI',data,40,1.2,1000,32,0,0,0)
    struct.pack_into('<ffifffiI',data,64,100,120,0,22.5,31,20,-1,0)
    return data

class Tests(unittest.TestCase):
    def test_timestamp_working_copy_removes_crlf_without_changing_ns(self):
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_timestamps_') as name:
            folder=pathlib.Path(name);original=folder/'source';original.write_bytes(b'1403636579763555584\r\n1403636579813555456\r\n')
            before=original.read_bytes();new=folder/'working'
            values=write_timestamps(original,new)
            self.assertEqual(original.read_bytes(),before)
            self.assertEqual(new.read_bytes(),b'1403636579763555584\n1403636579813555456\n')
            self.assertEqual(values,canonical_timestamps(new)[0])
    def test_crlf_rejected_before_spawn(self):
        runner=module('run_pc_slam');audited=module('golden_decision_audited')
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_crlf_') as name:
            folder=pathlib.Path(name);binary=folder/'fixture';binary.write_text('#!'+sys.executable+'\n')
            timestamp=folder/'timestamps.txt';timestamp.write_bytes(b'1000000000\r\n2000000000\r\n')
            argv=['test','--binary',str(binary),'--vocabulary',str(binary),'--yaml',str(binary),'--dataset',str(folder),'--timestamps',str(timestamp),'--output',str(folder/'run'),'--sequence','SYNTHETIC','--candidate','fixture','--cores',','.join(map(str,audited.cores()[0]))]
            topology=subprocess.check_output(['lscpu','-p=CPU,CORE,SOCKET'],text=True)
            with patch.object(sys,'argv',argv),patch.object(runner.subprocess,'check_output',return_value=topology),patch.object(runner.subprocess,'Popen') as spawn:
                self.assertEqual(runner.main(),1);spawn.assert_not_called()
            m=json.loads((folder/'run/run_metadata.json').read_text());self.assertEqual(m['completed_frames'],0);self.assertTrue(m['failure_reason'].startswith('INPUT_TIMESTAMP_FORMAT:'))
    def test_resume_preserves_input_failure_and_does_not_promote_success(self):
        resume=module('golden_decision_resume')
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_inherit_') as name:
            folder=pathlib.Path(name);metadata=folder/'run_metadata.json'
            atomic_json(metadata,dict(status='FAILED',completed_frames=0,exit_code=1))
            (folder/'TrackingStates.csv').write_text('frame_index,state_after\n');(folder/'run.log').write_text('Failed to load image at: bad filename')
            before=metadata.read_bytes();status,outcome=resume.inherited_run(folder,{},3682)
            self.assertEqual(status,'FAILED');self.assertEqual(outcome,'INPUT_SETUP_FAILURE_RETAINED_NO_RETRY');self.assertEqual(metadata.read_bytes(),before)
            atomic_json(metadata,dict(status='FINISHED',completed_frames=0,exit_code=0))
            with self.assertRaises(ValueError):resume.inherited_run(folder,{},3682)
    def test_protocol_and_corruptions(self):
        data=sample();self.assertEqual(packet(data,10**9,0,752,480,8,1000),1)
        for offset,fmt,value in [(16,'Q',10**9+1),(24,'I',960),(56,'i',2),(72,'i',8),(76,'f',float('nan')),(92,'I',1)]:
            bad=bytearray(data);struct.pack_into('<'+fmt,bad,offset,value)
            with self.assertRaises(ValueError):packet(bad,10**9,0,752,480,8,1000)
    def test_log_noise_is_not_progress(self):
        progress=CompletedProgress(0)
        self.assertFalse(progress.observe('GOLDEN_SEQUENCE_PROGRESS frames=3',1))
        self.assertFalse(progress.observe('new warning\nGOLDEN_SEQUENCE_PROGRESS frames=3',120))
        self.assertTrue(progress.observe('more warnings\nGOLDEN_SEQUENCE_PROGRESS frames=3',121))
        self.assertFalse(progress.observe('GOLDEN_SEQUENCE_PROGRESS frames=4',122))
    def test_failure_classification(self):
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_classify_') as name:
            folder=pathlib.Path(name);(folder/'hang_snapshot').mkdir()
            (folder/'hang_snapshot/threads.gdb.txt').write_text('Thread 1 #0 ORB_SLAM3::Tracking::Relocalization')
            (folder/'run.log').write_text('')
            m=dict(status='FAILED',failure_reason='NO_FRAME_PROGRESS_120S',completed_frames=145,stack_capture_ok=True,snapshot_saved_before_signal_utc='synthetic')
            self.assertEqual(classify(m,folder),'CANDIDATE_HANG_RETAINED')
            m['stack_capture_ok']=False
            with self.assertRaises(ValueError):classify(m,folder)
            with self.assertRaises(ValueError):classify(dict(status='FAILED',failure_reason='ELF_LINKAGE_CHECK'),folder)
    def test_schedule(self):
        audited=module('golden_decision_audited');items=audited.schedule()
        self.assertEqual(len(items),90)
        self.assertEqual(len({(i['dataset'],i['variant'],i['run_index']) for i in items}),90)
        for name in {i['dataset'] for i in items}:
            for variant in audited.VARIANTS:
                self.assertEqual([i['run_index'] for i in items if i['dataset']==name and i['variant']==variant],[1,2,3,4,5])
    def test_runner_waits_for_exclusive_lock(self):
        audited=module('golden_decision_audited')
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_lock_') as name:
            folder=pathlib.Path(name);binary=folder/'fixture'
            binary.write_text('#!'+sys.executable+'\nimport pathlib\npathlib.Path("TrackingStates.csv").write_text("frame_index,sequence_index,sequence_frame,timestamp_s,state_before,state_after\\n0,0,0,1,0,1\\n1,0,1,2,1,2\\n")\n');binary.chmod(0o755)
            timestamp=folder/'timestamps.txt';timestamp.write_text('1000000000\n2000000000\n')
            cmd=[sys.executable,str(HERE/'run_pc_slam.py'),'--binary',str(binary),'--vocabulary',str(binary),'--yaml',str(binary),'--dataset',str(folder),'--timestamps',str(timestamp),'--output',str(folder/'run'),'--sequence','SYNTHETIC','--candidate','fixture','--cores',','.join(map(str,audited.cores()[0])),'--wait-lock']
            with open('/tmp/orb_b3_pc_slam.lock','w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    time.sleep(0.5);self.assertIsNone(child.poll());self.assertFalse((folder/'run').exists())
                    fcntl.flock(lock,fcntl.LOCK_UN)
                    stdout,stderr=child.communicate(timeout=20)
                    self.assertEqual(child.returncode,0,stdout+stderr)
                    m=json.loads((folder/'run/run_metadata.json').read_text());self.assertEqual(m['status'],'FINISHED');self.assertEqual(m['completed_frames'],2)
                finally:
                    fcntl.flock(lock,fcntl.LOCK_UN)
                    if child.poll() is None:child.kill();child.communicate()
    def test_spawn_exception_has_terminal_metadata(self):
        runner=module('run_pc_slam');audited=module('golden_decision_audited')
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_spawn_') as name:
            folder=pathlib.Path(name);binary=folder/'fixture';binary.write_text('#!'+sys.executable+'\n')
            timestamp=folder/'timestamps.txt';timestamp.write_text('1000000000\n2000000000\n')
            argv=['test','--binary',str(binary),'--vocabulary',str(binary),'--yaml',str(binary),'--dataset',str(folder),'--timestamps',str(timestamp),'--output',str(folder/'run'),'--sequence','SYNTHETIC','--candidate','fixture','--cores',','.join(map(str,audited.cores()[0]))]
            topology=subprocess.check_output(['lscpu','-p=CPU,CORE,SOCKET'],text=True)
            with patch.object(sys,'argv',argv),patch.object(runner.subprocess,'check_output',return_value=topology),patch.object(runner.subprocess,'Popen',side_effect=OSError('synthetic spawn error')):
                self.assertEqual(runner.main(),1)
            m=json.loads((folder/'run/run_metadata.json').read_text());self.assertEqual(m['status'],'FAILED');self.assertTrue(m['failure_reason'].startswith('PROCESS_SPAWN:'))
    def test_all_failed_report_has_partial_metrics_and_empty_pair_csv(self):
        audited=module('golden_decision_audited')
        with tempfile.TemporaryDirectory(prefix='synthetic_g1_report_') as name:
            batch=pathlib.Path(name);(batch/'source').mkdir();(batch/'configs').mkdir()
            items=audited.schedule();datasets=[]
            for d in audited.DATASETS:
                datasets.append(dict(name=d['name'],kind='prepared',full_frames=4,path=str(batch),intrinsics_label='SYNTHETIC TEST ONLY'))
            atomic_json(batch/'configs/manifest.json',dict(datasets=datasets,plan=dict(variants=audited.VARIANTS)))
            for item in items:
                item['status']='FAILED';raw=batch/'runs'/item['folder'];raw.mkdir(parents=True)
                (raw/'TrackingStates.csv').write_text('frame_index,sequence_index,sequence_frame,timestamp_s,state_before,state_after\n0,0,0,1,0,1\n1,0,1,2,1,2\n2,0,2,3,2,3\n')
                calls=1 if item['variant']=='native' else 0
                (raw/'FeatureTimeStats.csv').write_text('frame_index,timestamp_ns,extractor_calls,inliers,count\n'+''.join('%d,%d,%d,%d,10\n'%(i,(i+1)*10**9,calls,20 if i==1 else -1) for i in range(3)))
                (raw/'MapStateStats.csv').write_text('frame_index,map_id,relocalized\n0,0,0\n1,0,0\n2,0,0\n')
                atomic_json(raw/'run_metadata.json',dict(status='FAILED',failure_reason='SYNTHETIC HANG'))
            atomic_json(batch/'batch_state.json',dict(completed=90,schedule=items))
            subprocess.run([sys.executable,str(HERE/'golden_report_audited.py'),'--batch-root',str(batch)],check=True,capture_output=True)
            rows=read_rows(batch/'report/results.csv')
            self.assertEqual(len(rows),90);self.assertTrue(all(r['status']=='FAILED' for r in rows))
            self.assertTrue(all(r['completed_frames']=='3' and r['maps']=='' and r['ate_rmse_m']=='' for r in rows))
            self.assertEqual(len(read_rows(batch/'report/native_differences.csv')),0)
            summaries=read_rows(batch/'report/summary_by_layers.csv')
            self.assertEqual(len(summaries),18);self.assertTrue(all(r['attempts']=='5' and r['valid']=='0' and r['failures']=='5' for r in summaries))

if __name__=='__main__':unittest.main(verbosity=2)
