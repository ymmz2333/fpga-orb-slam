"""Detached Windows coordinator: keep awake, restore power, expose terminal state."""
import argparse,datetime,json,pathlib,re,subprocess,time
from windows_awake import WindowsAwake
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);a=p.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch')
    out=PROJECT/'orb_frontend_golden/decision'/(a.batch+'_coordinator');out.mkdir(exist_ok=False)
    power=re.search(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace'))[0]
    target=json.loads((ROOT/'runtime/pc/power_change.json').read_text(encoding='utf-8-sig'))['selected'];awake=WindowsAwake()
    state=dict(status='STARTING',phase='preparing',batch=a.batch,planned=90,completed=0,failed_slots=0,previous_power_scheme=power,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():
        temp=out/'state.tmp';temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(out/'state.json')
    def linux(path):return subprocess.check_output(['wsl','-d','Ubuntu-20.04','-u','root','--','wslpath','-u',path.as_posix()],text=True).strip()
    save();child=None
    try:
        awake.acquire();subprocess.run(['powercfg','/setactive',target],check=True)
        command=['wsl','-d','Ubuntu-20.04','-u','root','--',linux(PROJECT/'orb_frontend_golden/.venv-wsl/bin/python'),linux(ROOT/'scripts/h_round.py'),'--batch',a.batch]
        with (out/'pipeline.log').open('wb') as log:
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT);state.update(status='RUNNING',phase='decision_pipeline',child_pid=child.pid);save()
            while child.poll() is None:
                time.sleep(15)
                f=PROJECT/'orb_frontend_golden/decision'/a.batch/'batch_state.json'
                try:s=json.loads(f.read_text(encoding='utf-8'));state.update(completed=s['completed'],failed_slots=s['failed_slots'],decision_phase=s['phase']);save()
                except (FileNotFoundError,json.JSONDecodeError):pass
        s=json.loads((PROJECT/'orb_frontend_golden/decision'/a.batch/'batch_state.json').read_text(encoding='utf-8'))
        if child.returncode or s['status']!='FINISHED_AWAIT_LAYER_DECISION':raise RuntimeError(s.get('error','Pipeline exit='+str(child.returncode)))
        state.update(status=s['status'],phase='await_user_layer_choice',completed=s['completed'],failed_slots=s['failed_slots'])
    except Exception as error:state.update(status='FAILED',error=str(error))
    finally:
        state['power_restore_exit_code']=subprocess.run(['powercfg','/setactive',power],capture_output=True).returncode;awake.release();state['awake_released']=True;state['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    return 0 if state['status']=='FINISHED_AWAIT_LAYER_DECISION' else 1
if __name__=='__main__':raise SystemExit(main())
