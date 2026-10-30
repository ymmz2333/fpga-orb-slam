"""Replay one recorded compile command with diagnostics, preserving compiler/optimization.

No edits to source or flags governing optimization. -freport-bug/-save-temps
only retain diagnostic/reproducer material. Object output is isolated.
"""
import argparse,json,os,pathlib,shlex,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(); p.add_argument('--commands',type=pathlib.Path,required=True)
p.add_argument('--source-suffix',required=True); p.add_argument('--output',type=pathlib.Path,required=True)
a=p.parse_args(); entry=next(e for e in json.loads(a.commands.read_text()) if e['file'].endswith(a.source_suffix))
if a.output.exists(): raise SystemExit('Refusing reused reproducer output')
a.output.mkdir(parents=True); command=entry.get('arguments') or shlex.split(entry['command'])
command[command.index('-o')+1]=str((a.output/'reproducer.o').resolve())
command+=['-freport-bug','-save-temps=obj']
(a.output/'command.json').write_text(json.dumps(dict(original=entry,replay=command),indent=2))
environment=os.environ.copy(); environment['TMPDIR']=str(a.output.resolve())
code=subprocess.run([sys.executable,str(ROOT/'scripts/measure_compile.py'),'--output',str(a.output.resolve()/'measurement'),'--']+command,
    cwd=entry['directory'],env=environment).returncode
raise SystemExit(code)
