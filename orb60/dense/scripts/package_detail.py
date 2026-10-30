"""Package the refined cloud, actual keyframe colors, replay index and measured evidence."""
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    project=Path(__file__).resolve().parents[3];base=project/'orb60/build/dense'
    result=base/'room_full_detail';target=base/'orb60_dense_detail_result.zip'
    files=[p for p in result.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and p.name!='full_rgb_export.ply']
    manifest={str(p.relative_to(result)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for path in files:archive.write(path,'room_full_detail/'+str(path.relative_to(result)).replace('\\','/'))
        archive.writestr('SHA256.json',json.dumps(manifest,indent=2)+'\n')
        archive.writestr('READ_ME.txt','1086538 colored points; same-run final poses and 130 original-color keyframes.\n'
            'Open room_full_detail/result.json in ORB Studio. For full 2273-frame playback select the original matching MP4;\n'
            'the video is not duplicated in this archive. Without it, genuine keyframes are replayed.\n'
            'The paired source snapshot is in source_used. See PLAYBACK_AND_DENSITY.md in the implementation package.\n')
    with zipfile.ZipFile(target) as archive:assert archive.testzip() is None
    record=dict(file=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),files=len(files))
    (base/'detail_archive.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))


if __name__=='__main__':main()
