"""Local desktop session: display policy and the existing manual controller."""
import argparse,json,os,socket,subprocess,time
from pathlib import Path


def screen_policy(execute):
    commands=[['gsettings','set','org.gnome.desktop.session','idle-delay','0'],
              ['gsettings','set','org.gnome.desktop.screensaver','lock-enabled','false'],
              ['gsettings','set','org.gnome.settings-daemon.plugins.power','sleep-inactive-ac-type','nothing'],
              ['gsettings','set','org.gnome.settings-daemon.plugins.power','sleep-inactive-battery-type','nothing'],
              ['xset','s','off'],['xset','s','noblank'],['xset','dpms','force','on'],['xset','-dpms']]
    for command in commands:execute(command,check=False)
    query=execute(['xrandr','--current'],check=True,capture_output=True,text=True).stdout
    if 'DP-1 connected' in query and '1024x768' in query:
        execute(['xrandr','--output','DP-1','--mode','1024x768','--rate','60','--primary'],check=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();root=a.root.resolve()
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();folder=root/'startup_runtime'/boot
    logroot=root/'desktop_startup';logroot.mkdir(exist_ok=True);report=logroot/(boot+'.json')
    state=dict(status='WAITING_PLATFORM',boot_id=boot,display=os.environ.get('DISPLAY'),automatic_mapping=False)
    def save():report.write_text(json.dumps(state,indent=2)+'\n')
    def execute(command,**kwargs):return subprocess.run(command,timeout=15,**kwargs)
    save()
    try:
        screen_policy(execute)
        deadline=time.monotonic()+240
        while True:
            if (folder/'PLATFORM.json').exists():
                platform=json.loads((folder/'PLATFORM.json').read_text())
                if platform['status']=='FAILED':raise RuntimeError('Cold-boot platform failed: '+platform.get('error',''))
                if platform['status']=='READY' and platform['boot_id']==boot:break
            if time.monotonic()>deadline:raise TimeoutError('Boot platform not ready; no hardware reload from desktop')
            time.sleep(.5)
        # The panel owns the peer wait. It must open even while cables are being
        # changed; no fixed network-wait deadline can terminate the desktop UI.
        state['status']='RUNNING_MANUAL_SESSION';save()
        child=subprocess.Popen(['bash',str(root/'sources/orb60/kv260/run_manual_session.sh')],cwd=root/'sources')
        state['pid']=child.pid;save();code=child.wait()
        state.update(status='EXITED',exit_code=code);return code
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:save()


if __name__=='__main__':raise SystemExit(main())
