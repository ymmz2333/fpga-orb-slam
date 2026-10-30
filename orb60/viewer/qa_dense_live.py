"""Observe an actual running FPGA + SLAM + RK NPU session; no replayed/generated map fixtures."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from PySide6 import QtWidgets,QtCore
from app import Window


def main():
    p=argparse.ArgumentParser();p.add_argument('--connect',required=True)
    p.add_argument('--video',required=True,type=Path);p.add_argument('--frame-map',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--seconds',type=float,default=90)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication([])
    args=argparse.Namespace(connect='',dense_live=a.connect,frame_map=a.frame_map,video=a.video,recording=None,
                            dense=None,metrics=a.output/'desktop_metrics.json')
    w=Window(args);w.show();samples=[];poses=[];first_chunk_time=None;start=time.perf_counter();problem=[]
    timer=QtCore.QTimer();timer.setInterval(100)
    def finish():timer.stop();w.close();app.quit()
    def sample():
        nonlocal first_chunk_time
        try:
            layer=w.live_cloud;chunks,points,displayed=layer.counts()
            frame=w.current.meta['frame_index'] if w.current else -1
            row=dict(seconds=time.perf_counter()-start,frame=frame,map_id=w.scene.map_id,chunks=chunks,points=points,
                     displayed=displayed,uploads=layer.uploads,pose_updates=layer.pose_updates)
            row['position']=w.scene.pose[:3,3].tolist() if w.scene.pose_valid else None
            samples.append(row)
            if w.scene.pose_valid:poses.append(w.scene.pose[:3,3].copy())
            if chunks and first_chunk_time is None:
                first_chunk_time=row['seconds'];w.grab().save(str(a.output/'first_points.png'))
            if chunks>=5 and not (a.output/'growing_map.png').is_file():w.grab().save(str(a.output/'growing_map.png'))
            if w.live.state=='ERROR':raise RuntimeError(w.live.error or 'Actual processing failed')
            if w.live.state=='COMPLETED':w.grab().save(str(a.output/'final_map.png'));finish()
            elif row['seconds']>a.seconds:raise TimeoutError('Actual live processing did not complete within test window')
        except Exception as exc:problem.append(str(exc));finish()
    timer.timeout.connect(sample);timer.start();app.exec()
    (a.output/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
    if problem:raise RuntimeError('; '.join(problem))
    assert samples and max(s['chunks'] for s in samples)>=3,'No actual growing dense map'
    assert first_chunk_time<samples[-1]['seconds']-2,'Cloud appeared only after processing ended'
    assert max(s['displayed'] for s in samples)<=200000
    assert len(poses)>10 and np.max(np.ptp(poses,axis=0))>.02,'Camera did not move'
    retained=[(left,right) for left,right in zip(samples,samples[1:]) if left['map_id']==right['map_id'] and left['points']>0
              and left['frame']<right['frame'] and left['uploads']==right['uploads']]
    assert retained,'Every camera update uploaded a complete point cloud'
    for left,right in zip(samples,samples[1:]):
        if left['map_id']==right['map_id']:assert left['points']<=right['points']
    report=dict(status='PASS',actual_processing=True,offline_final_cloud_loaded=False,
                first_points_seconds=first_chunk_time,final_points=samples[-1]['points'],final_chunks=samples[-1]['chunks'],
                last_displayed_frame=samples[-1]['frame'],camera_updates_without_point_upload=len(retained),
                display_cap=max(s['displayed'] for s in samples),camera_translation_span=np.ptp(poses,axis=0).tolist())
    (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
