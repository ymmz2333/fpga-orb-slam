"""Scoped power/awake for the finite counter-only reproduction."""
import argparse,json,pathlib,re,subprocess,sys
from windows_awake import WindowsAwake
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
p=argparse.ArgumentParser();p.add_argument('--fixed',action='store_true');a=p.parse_args()
before=re.search(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace'))[0]
target=json.loads((ROOT/'runtime/pc/power_change.json').read_text(encoding='utf-8-sig'))
awake=WindowsAwake();awake.acquire()
try:
    subprocess.run(['powercfg','/setactive',target['selected']],check=True)
    def linux(p):return subprocess.check_output(['wsl','-d','Ubuntu-20.04','-u','root','--','wslpath','-u',p.as_posix()],text=True).strip()
    command=['wsl','-d','Ubuntu-20.04','-u','root','--',linux(PROJECT/'orb_frontend_golden/.venv-wsl/bin/python'),
        linux(ROOT/'scripts/h1_probe.py'),'--output',linux(PROJECT/'orb_frontend_golden/decision'/('H1_fixed_probe_20261006_01' if a.fixed else 'H1_counter_probe_20261006_01'))]
    if a.fixed:command.append('--fixed')
    result=subprocess.run(command)
finally:
    subprocess.run(['powercfg','/setactive',before],check=True);awake.release()
raise SystemExit(result.returncode)
