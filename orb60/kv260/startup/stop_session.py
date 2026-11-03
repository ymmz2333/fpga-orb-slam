"""Maintenance shutdown: request EOS/drain from this user's actual controller."""
import argparse,json,os,time,uuid
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--timeout',type=float,default=110);a=p.parse_args();root=a.root.resolve()
    if not 5<=a.timeout<=300:raise ValueError('Explicit bounded drain timeout required')
    pending=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if proc.stat().st_uid!=os.getuid():continue
            args=(proc/'cmdline').read_bytes().decode().split('\0')
            if 'orb60.kv260.manual_control' not in args:continue
            folder=Path(args[args.index('--folder')+1]).resolve()
            if not folder.is_relative_to(root/'manual_sessions'):continue
            queue=folder/'commands';name='%020d_%s'%(time.monotonic_ns(),uuid.uuid4().hex)
            tmp=queue/(name+'.tmp');tmp.write_text(json.dumps(dict(action='quit')));tmp.replace(queue/(name+'.json'));pending.append(proc)
        except (OSError,ValueError,IndexError):continue
    deadline=time.monotonic()+a.timeout
    while any(p.exists() for p in pending):
        if time.monotonic()>deadline:raise TimeoutError('Manual controller did not drain; inspect its logs')
        time.sleep(.2)
    return 0


if __name__=='__main__':raise SystemExit(main())
