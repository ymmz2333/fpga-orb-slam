"""PS-only user-requested restart via a helper outside the application service."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path


def save(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def request(root,gui_pid):
    root=Path(root).resolve();folder=root/'manual_restart_requests';folder.mkdir(exist_ok=True)
    token=uuid.uuid4().hex;report=folder/(token+'.json')
    save(report,dict(status='QUEUED',gui_pid=gui_pid))
    script=Path(__file__).resolve()
    command=['systemd-run','--user','--collect','--unit=orb60-manual-restart-'+token,
             '/usr/bin/python3',str(script),'--root',str(root),'--report',str(report),'--gui-pid',str(gui_pid)]
    subprocess.run(command,check=True,capture_output=True,text=True,timeout=15)
    return report


def run(root,report,gui_pid):
    root=Path(root).resolve();report=Path(report).resolve()
    if report.parent!=root/'manual_restart_requests' or gui_pid<=1:raise ValueError('Owned restart request required')
    record=dict(status='STOPPING_AND_SAVING',gui_pid=gui_pid,pl_reload=False,map_deleted=False)
    save(report,record)
    try:
        # A separate transient user service survives stopping the GUI service.
        subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('startup')/'stop_session.py'),
                        '--root',str(root),'--timeout','300'],check=True,timeout=310)
        deadline=time.monotonic()+15
        while Path('/proc',str(gui_pid)).exists():
            try:args=(Path('/proc')/str(gui_pid)/'cmdline').read_bytes().split(b'\0')
            except OSError:break
            if b'orb60.kv260.manual_gui' not in args:break # PID was reused.
            if time.monotonic()>deadline:raise TimeoutError('Old control panel has not released its session')
            time.sleep(.2)
        record['status']='STARTING_SERVICE';save(report,record)
        subprocess.run(['systemctl','--user','restart','orb60-manual-session.service'],check=True,timeout=140)
        deadline=time.monotonic()+90
        while True:
            live=[]
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit():continue
                try:a=(proc/'cmdline').read_bytes().decode().split('\0')
                except OSError:continue
                if 'orb60.kv260.manual_control' in a:
                    folder=Path(a[a.index('--folder')+1]).resolve()
                    if folder.is_relative_to(root/'manual_sessions') and (folder/'status.json').exists():
                        live.append((proc,folder,json.loads((folder/'status.json').read_text())))
            if len(live)==1 and live[0][2]['phase'] in ('LOCALIZING','IDLE','WAIT_NETWORK','ERROR'):
                proc,folder,state=live[0]
                record.update(status='RESTARTED_WITH_ERROR' if state['phase']=='ERROR' else 'RESTARTED',
                              controller_pid=int(proc.name),session=str(folder),phase=state['phase'],message=state['message'])
                break
            if time.monotonic()>deadline:raise TimeoutError('New controller did not become ready')
            time.sleep(.5)
    except BaseException as e:record.update(status='FAILED',error=repr(e));raise
    finally:save(report,record)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--gui-pid',type=int,required=True)
    a=p.parse_args();run(a.root,a.report,a.gui_pid)
