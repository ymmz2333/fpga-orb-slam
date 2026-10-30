"""One bounded first-run startup gate; no continuing experiment log polling."""
import argparse,csv,json,os,pathlib,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); a=p.parse_args()
base=ROOT/'runtime/c'/a.batch
for _ in range(55):
    if (base/'batch_state.json').exists():
        state=json.loads((base/'batch_state.json').read_text())
        if state['status']!='RUNNING': raise SystemExit('Startup failed: '+state['status']+' '+state.get('reason',''))
        if state.get('current'):
            folder=base/state['current']; path=folder/'run_metadata.json'
            if path.exists():
                meta=json.loads(path.read_text())
                if meta['status']=='RUNNING' and (folder/'TrackingStates.csv').exists():
                    with (folder/'TrackingStates.csv').open() as f: frames=list(csv.DictReader(f))
                    if len(frames)>=1:
                        print('C_STARTED first=%s processed_buffered=%d OK=%d pid=%s affinity=%s planned=%d'%
                            (state['current'],len(frames),sum(r['state_after']=='2' for r in frames),meta['slam_pid'],sorted(os.sched_getaffinity(meta['slam_pid'])),state['planned']))
                        print('CPU=%s DMC=%s actual_hz=%s temperature_mc=%s'%
                            (meta['governors_during_run'],meta['dmc_governor_during'],meta['before_sensors']['dmc_cur_hz'],meta['before_sensors']['thermal_zone0_temp_mc']))
                        raise SystemExit(0)
    time.sleep(1)
raise SystemExit('Startup unconfirmed after 55s; do not relaunch batch')
