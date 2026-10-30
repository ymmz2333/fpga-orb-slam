"""Detached launcher for the audited wrapper of the unchanged G1 90-slot plan."""
import argparse
import json
import pathlib
import re
import subprocess
import sys

EXPERIMENT=pathlib.Path(__file__).resolve().parents[1]
PROJECT=EXPERIMENT.parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--acceptance',required=True,type=pathlib.Path);p.add_argument('--resume-from',type=pathlib.Path);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch name')
    root=PROJECT/'orb_frontend_golden/decision'
    if (root/a.batch).exists():raise ValueError('Existing batch cannot be relaunched')
    if json.loads(a.acceptance.read_text())['status']!='PASSED':raise ValueError('Audit not passed')
    log=root/(a.batch+'_launcher.log')
    with log.open('xb') as stream:
        command=[sys.executable,str(EXPERIMENT/'scripts'/('golden_decision_resume.py' if a.resume_from else 'golden_decision_audited.py')),'--batch',a.batch,'--acceptance',str(a.acceptance)]
        if a.resume_from:command+=['--resume-from',str(a.resume_from)]
        else:command+=['--start-after-delivery']
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    print(json.dumps(dict(pid=process.pid,batch=a.batch,log=str(log),acceptance=str(a.acceptance))))

if __name__=='__main__':main()
