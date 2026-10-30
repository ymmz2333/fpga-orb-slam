"""Check real retained short-run reporting/ATE paths before any full B3 slot."""
import argparse
import decimal
import json
import pathlib
import shutil
import sys
from golden_audit_support import atomic_json,read_rows
from golden_report_audited import frame_facts
from evaluate_a2 import evaluate
from finish_c import compare

EXPERIMENT=pathlib.Path(__file__).resolve().parents[1]
PROJECT=EXPERIMENT.parents[1]
GOLDEN=PROJECT/'orb_frontend_golden'
sys.path.insert(0,str(GOLDEN/'scripts'))
from common import DATASETS

def main():
    p=argparse.ArgumentParser();p.add_argument('--previous',required=True,type=pathlib.Path);p.add_argument('--output',required=True,type=pathlib.Path);a=p.parse_args()
    a.output.mkdir(exist_ok=False);result=dict(status='RUNNING',scope='Retained short runs; not full B3 measurements')
    raw=a.previous/'MH01_native_flushed600_01';folder=a.output/'mh01_analysis';shutil.copytree(raw,folder)
    facts=frame_facts(raw,dict(kind='euroc',path=str(DATASETS[0]['path']),full_frames=600),dict(status='FINISHED',variant='native'),folder)
    ok={float(r['timestamp_s']) for r in read_rows(folder/'TrackingStates.csv') if r['state_after']=='2'}
    trajectory=folder/'f_MH01.txt'
    if not trajectory.exists():shutil.copy2(folder/'f_MH01_native_flushed600_01.txt',trajectory)
    lines=[line for line in trajectory.read_text().splitlines() if line.split() and float(decimal.Decimal(line.split()[0]))*1e-9 in ok]
    trajectory.write_text('\n'.join(lines)+'\n')
    ate=evaluate(folder,DATASETS[0]['path']);assert 'NumPy cross-check passed' in ate['evaluation_method']
    result.update(mh01_frames=facts['completed_frames'],ate_crosscheck=ate['evaluation_method'],ate_associated=ate['associated_poses'])
    pairs=[]
    for d in DATASETS[1:]:
        pair=compare(a.previous/(d['name']+'_native_replay150'),a.previous/(d['name']+'_V0_inject150'))
        pairs.append(dict(dataset=d['name'],**pair))
    result.update(status='PASSED',tello_sim3_pairs=pairs)
    atomic_json(a.output/'state.json',result);print('REAL_SHORT_ANALYSIS_PASS MH01 evo+NumPy; Tello Sim3 comparison')
if __name__=='__main__':main()
