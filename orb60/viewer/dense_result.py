"""Separate offline result files; ORBVIZ01 is intentionally untouched."""
import json
import hashlib
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dense.ply import read_ply


class DenseResult:
    def __init__(self,path,map_id=None):
        path=Path(path)
        if path.is_dir():path=path/'result.json'
        report=json.loads(path.read_text(encoding='utf-8-sig'))
        if 'maps' in report:
            candidates=[m for m in report['maps'] if m.get('points',0)>0 and (map_id is None or m['map_id']==map_id)]
            if not candidates:raise ValueError('此结果没有可显示的有效稠密地图')
            chosen=candidates[0];path=path.parent/('map_%d'%chosen['map_id'])/'result.json'
            report=json.loads(path.read_text())
        self.report=report;self.root=path.parent;self.path=path
        self.cloud=self._file(report['cloud']);self.xyz,self.rgb=read_ply(self.cloud)
        self.sparse_xyz,self.sparse_rgb=read_ply(self._file(report['sparse']))
        poses=json.loads(self._file(report['poses']).read_text())
        self.poses=np.array([p['twc'] for p in poses],np.float32).reshape(-1,4,4)
        self.replay=None
        if report.get('replay'):
            self.replay=json.loads(self._file(report['replay']).read_text())
            frames=self.replay['frames']
            if not frames or any(a['pts_s']>=b['pts_s'] for a,b in zip(frames,frames[1:])):
                raise ValueError('Invalid replay timestamps')
            for frame in frames:
                if 'rgb' in frame:self._file(frame['rgb'])
        # Display sampling never changes the full export payload.
        # Stable random sampling avoids visible stripes from lexicographically sorted voxels.
        self.indices=(np.sort(np.random.RandomState(1729).choice(len(self.xyz),200000,replace=False))
                      if len(self.xyz)>200000 else np.arange(len(self.xyz)))

    def _file(self,name):
        result=(self.root/name).resolve()
        if self.root.resolve() not in result.parents:raise ValueError('Invalid dense result artifact path')
        return result

    def sampled(self):return self.xyz[self.indices],self.rgb[self.indices]

    def verify_video(self,path):
        h=hashlib.sha256()
        with Path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        if not self.replay or h.hexdigest()!=self.replay['video_sha256']:
            raise ValueError('所选视频不是这份建模结果的原片，不能同步回放')
