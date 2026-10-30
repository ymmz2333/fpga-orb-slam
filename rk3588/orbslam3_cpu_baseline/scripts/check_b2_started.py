"""One bounded first-run initialization gate; no continuing batch log polling."""
import argparse,csv,json,os,pathlib,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--folder');a=p.parse_args();base=ROOT/'runtime/b2'/a.batch
for _ in range(55):
    if (base/'batch_state.json').exists():
        state=json.loads((base/'batch_state.json').read_text(encoding='utf-8'))
        if state['status']!='RUNNING':raise SystemExit('Startup stopped: '+state['status']+' '+state.get('reason',''))
        first=next(i for i in state['schedule'] if i['folder']==a.folder) if a.folder else state['schedule'][0]
        folder=base/'runs'/first['folder'];path=folder/'run_metadata.json'
        if path.exists():
            meta=json.loads(path.read_text(encoding='utf-8'))
            frames=[]
            if (folder/'TrackingStates.csv').exists():
                with (folder/'TrackingStates.csv').open() as f:frames=list(csv.DictReader(f))
            ok=sum(r.get('state_after')=='2' for r in frames)
            if ok and meta['status'] in ('RUNNING','FINISHED'):
                affinity=sorted(os.sched_getaffinity(meta['slam_pid'])) if meta['status']=='RUNNING' else meta.get('observed_affinity')
                print('B2_STARTED first=%s buffered_frames=%d OK=%d affinity=%s planned=%d'%(first['folder'],len(frames),ok,affinity,state['planned']))
                print('CPU=%s DMC=%s actual_hz=%s temperature_mc=%s'%(meta['governors_during_run'],meta['dmc_governor_during'],meta['before_sensors']['dmc_cur_hz'],meta['before_sensors']['thermal_zone0_temp_mc']))
                raise SystemExit(0)
    time.sleep(1)
raise SystemExit('First-run initialization unconfirmed after 55s; do not relaunch batch')
