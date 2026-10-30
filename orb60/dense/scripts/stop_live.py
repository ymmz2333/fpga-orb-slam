"""Stop only one owned live session; wait for cleanup before allowing a restart."""
import argparse
import json
from pathlib import Path
import time

p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
root=a.run.resolve();allowed=(Path.cwd()/'runtime/dense/live_sessions').resolve()
if root.parent!=allowed:raise ValueError('Unexpected live session directory')
deadline=time.monotonic()+40
while not root.exists() and time.monotonic()<deadline:time.sleep(.1)
if not root.is_dir():raise RuntimeError('Live session never created its directory')
(root/'stop').touch()
while not (root/'done.json').is_file():
    if time.monotonic()>deadline:raise TimeoutError('Old live session did not acknowledge cleanup; restart refused')
    time.sleep(.1)
print(json.dumps(dict(status='STOPPED',run=root.name,cleanup=json.loads((root/'done.json').read_text()))))
