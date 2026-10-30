"""Manual one-line status, usable in SSH or an HDMI desktop terminal."""
import argparse,json,pathlib,re
p=argparse.ArgumentParser();p.add_argument('--batch',required=True);a=p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise SystemExit('Invalid batch ID')
root=pathlib.Path(__file__).resolve().parent.parent
s=json.loads((root/'runtime/b2'/a.batch/'batch_state.json').read_text(encoding='utf-8'))
print('status=%s completed=%s/%s phase=%s current=%s'%(s['status'],s['completed'],s['planned'],s['phase'],s.get('current')))
if s.get('reason'):print('reason='+s['reason'])
