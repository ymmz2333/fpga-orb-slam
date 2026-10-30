#!/usr/bin/env python3
"""Short authorized DMC performance/restore probe, no SLAM or benchmark numbers."""
import argparse
import json
import pathlib
import subprocess
import time
p=argparse.ArgumentParser(); p.add_argument('--output',required=True); a=p.parse_args()
out=pathlib.Path(a.output); out.mkdir(parents=True,exist_ok=False)
dmc=pathlib.Path('/sys/class/devfreq/dmc')
original=(dmc/'governor').read_text().strip()
available=list(map(int,(dmc/'available_frequencies').read_text().split()))
minimum=int((dmc/'min_freq').read_text()); maximum=int((dmc/'max_freq').read_text())
result=dict(original_governor=original,available_hz=available,min_hz=minimum,max_hz=maximum,status='FAILED')
def setgov(value):
    subprocess.run(['sudo','-n','tee',str(dmc/'governor')],input=value+'\n',text=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
try:
    if maximum!=max(available): raise RuntimeError('DMC has a cap below highest available frequency')
    setgov('performance'); time.sleep(1)
    result['performance_governor']=(dmc/'governor').read_text().strip()
    result['samples_hz']=[]
    for index in range(5):
        result['samples_hz'].append(int((dmc/'cur_freq').read_text())); time.sleep(0.5)
    if result['performance_governor']!='performance' or any(v!=max(available) for v in result['samples_hz']):
        raise RuntimeError('Performance did not hold highest frequency')
    result['status']='PASS'
except Exception as error: result['error']=str(error)
finally:
    setgov(original)
    result['after_governor']=(dmc/'governor').read_text().strip()
    result['restored']=(result['after_governor']==original and int((dmc/'min_freq').read_text())==minimum
                        and int((dmc/'max_freq').read_text())==maximum)
    (out/'dmc_control.json').write_text(json.dumps(result,indent=2))
print('DMC_PREFLIGHT status=%s samples_hz=%s restored=%s'%(result['status'],result.get('samples_hz'),result['restored']))
if result['status']!='PASS' or not result['restored']: raise SystemExit(1)
