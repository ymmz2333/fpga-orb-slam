"""KV260-local ORB Studio: separate GUI and bounded read-only SLAM telemetry."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def wake_x11_display(env):
    # On this board, Mali waits inside the first glClear while X11 DPMS is off.
    # Wake only the requested native desktop; do not disable its power policy.
    if sys.platform.startswith('linux') and platform.machine()=='aarch64' and env.get('DISPLAY') and env.get('QT_QPA_PLATFORM','xcb')=='xcb':
        try:
            query=subprocess.run(['xset','-q'],env=env,capture_output=True,text=True,timeout=5)
            if query.returncode==0 and 'Monitor is Off' in query.stdout:
                subprocess.run(['xset','dpms','force','on'],env=env,capture_output=True,check=True,timeout=5)
                print('KV260_GUI_DISPLAY_WOKEN_FROM_DPMS',flush=True)
        except FileNotFoundError:
            print('KV260_GUI_DPMS_CHECK_UNAVAILABLE: xset is absent',flush=True)


def commands(args):
    viewer=ROOT/'orb60/viewer'
    entry=['-m','orb60.kv260.gui_worker'] if args.renderer=='gles2' else [str(viewer/'app.py')]
    command=[sys.executable,*entry,'--processor','KV260 PS','--config',str(ROOT/'orb60/build/local/kv260_gui.json')]
    if os.getenv('ORB60_GUI_PROFILE'):
        # Explicit diagnostic run only; profile the actual worker, not its launcher.
        command=[sys.executable,'-m','cProfile','-o',os.environ['ORB60_GUI_PROFILE'],*command[1:]]
    bridge=None
    if args.recording:command+=['--recording',str(args.recording)]
    elif args.dense:command+=['--dense',str(args.dense)]
    elif getattr(args,'dense_live',None):command+=['--dense-live',args.dense_live]
    else:
        if not args.telemetry:raise ValueError('Specify --telemetry, --recording or --dense')
        command+=['--connect',f'127.0.0.1:{args.port}']
        bridge=[sys.executable,str(viewer/'bridge.py'),'--directory',str(args.telemetry),'--bind','127.0.0.1','--port',str(args.port)]
    if args.video:command+=['--video',str(args.video)]
    if getattr(args,'frame_map',None):command+=['--frame-map',str(args.frame_map)]
    if args.screenshot:command+=['--screenshot',str(args.screenshot)]
    if getattr(args,'screenshot_frame',-1)>=0:command+=['--screenshot-frame',str(args.screenshot_frame)]
    if args.exit_after:command+=['--exit-after',str(args.exit_after)]
    if args.metrics:command+=['--metrics',str(args.metrics),'--desktop-status',str(args.metrics.with_name(args.metrics.stem+'_desktop_status.json'))]
    if not getattr(args,'embedded_maps',False):command+=['--separate-maps']
    return command,bridge


def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--telemetry',type=Path);source.add_argument('--recording',type=Path);source.add_argument('--dense',type=Path)
    source.add_argument('--dense-live',help='Local dense stream, e.g. 127.0.0.1:18786')
    p.add_argument('--video',type=Path);p.add_argument('--port',type=int,default=8765)
    p.add_argument('--frame-map',type=Path,help='Exact timestamp/source frame mapping supplied by the local producer')
    p.add_argument('--saved-pl-replay',action='store_true',help='Label diagnostic PS telemetry from saved PL features')
    p.add_argument('--renderer',choices=['gles2','gles','desktop','egl-raster'],default='gles2')
    p.add_argument('--embedded-maps',action='store_true',help='Explicit QA/alternate layout; separate map windows are the default')
    p.add_argument('--allow-software-renderer-for-test',action='store_true',help='QA only; production requires a hardware GPU')
    p.add_argument('--screenshot',type=Path);p.add_argument('--metrics',type=Path);p.add_argument('--exit-after',type=float,default=0)
    p.add_argument('--screenshot-frame',type=int,default=-1)
    args=p.parse_args();command,bridge=commands(args)
    if args.saved_pl_replay and not args.telemetry:p.error('--saved-pl-replay requires --telemetry')
    if args.metrics:args.metrics.parent.mkdir(parents=True,exist_ok=True)
    if args.screenshot:args.screenshot.mkdir(parents=True,exist_ok=True)
    # Respect the logged-in desktop's DISPLAY / Wayland settings. No xhost or
    # global graphics configuration changes; an absent desktop fails explicitly.
    if sys.platform.startswith('linux') and not (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY') or os.getenv('QT_QPA_PLATFORM')=='offscreen'):
        p.error('No local desktop session; run in the KV260 HDMI desktop terminal')
    env=os.environ.copy();env['ORB60_VIEWER_RENDERER']=args.renderer
    env['QT_OPENGL']='es2' if args.renderer in ('gles2','gles','egl-raster') else 'desktop'
    env['ORB60_GUI_QA_SOFTWARE']='1' if args.allow_software_renderer_for_test else '0'
    if args.saved_pl_replay:env['ORB60_GUI_SOURCE_SCOPE']='saved_pl_replay'
    if sys.platform.startswith('linux') and args.renderer=='gles2':env.setdefault('QT_XCB_GL_INTEGRATION','xcb_egl')
    wake_x11_display(env)
    child=subprocess.Popen(bridge,env=env) if bridge else None
    try:return subprocess.call(command,env=env)
    finally:
        if child:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':raise SystemExit(main())
