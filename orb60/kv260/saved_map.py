"""Persist sealed map bytes before publishing the selected-map pointer."""
import json,os,uuid
from pathlib import Path


def sync_directory(path):
    if os.name=='nt':return
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def commit_selection(root,handoff,camera_sha256):
    root,handoff=Path(root),Path(handoff)
    # A successful rename alone does not make preceding map writes durable.
    for path in handoff.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:os.fsync(stream.fileno())
    directories=[p for p in handoff.rglob('*') if p.is_dir()]
    for path in sorted(directories,key=lambda p:len(p.parts),reverse=True):sync_directory(path)
    sync_directory(handoff);sync_directory(handoff.parent)
    pointer=root/'manual_latest_map.json'
    temporary=root/('manual_latest_map.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(dict(handoff=str(handoff),camera_sha256=camera_sha256),stream,indent=2)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        temporary.replace(pointer);sync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)
