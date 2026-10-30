"""Own-window integration QA. Consumes only the actual current FPGA/NPU stream."""
import argparse
import json
from pathlib import Path
import time
from PySide6 import QtWidgets,QtCore
from app import Window
import numpy as np
from OpenGL.GL import GL_DEPTH_TEST

p=argparse.ArgumentParser()
p.add_argument('--dense-live',required=True);p.add_argument('--video',type=Path,required=True)
p.add_argument('--frame-map',type=Path,required=True);p.add_argument('--metrics',type=Path,required=True)
p.add_argument('--control-file',type=Path,required=True);p.add_argument('--exit-after',type=float,default=140)
p.add_argument('--qa-frames',type=int,default=900)
a=p.parse_args();a.connect='';a.recording=None;a.dense=None
app=QtWidgets.QApplication([]);w=Window(a);w.resize(1200,680);w.show()
folder=a.metrics.parent.parent/'controls_restart_v2';folder.mkdir(exist_ok=True)
stage=3 if (folder/'completed_restart.json').exists() else (1 if not (folder/'restart_once.json').exists() else 2)
start=time.monotonic();rows=[];errors=[];done=False;wait_until=None
timer=QtCore.QTimer();timer.setInterval(100)

def sample():
    global done,wait_until
    if done:return
    try:
        index=w.current.meta['frame_index'] if w.current else -1
        rows.append(dict(seconds=time.monotonic()-start,frame=index,state=w.live.state,
                         sparse_points=len(w.scene.points),dense_points=w.live_cloud.counts()[1]))
        assert not w.live_failure,w.live_failure
        if index>=120 and stage==1:
            assert np.array_equal(w.sparse_view.path.pos,w.map_view.path.pos)
            assert w.map_view.path._GLGraphicsItem__glOpts[GL_DEPTH_TEST] is False
            assert w.sparse_view.cloud.pos is not None and len(w.sparse_view.cloud.pos)>0
            r=w.raw.image_rect();assert abs(r.width()/r.height()-4/3)<.02
            assert w.height()<=680 and w.play.mapTo(w,w.play.rect().bottomRight()).y()<w.height()
            w.grab().save(str(folder/'four_views_before_restart.png'))
            (folder/'restart_once.json').write_text(json.dumps(dict(status='REQUESTED',frame=index,session=str(a.metrics.parent))))
            done=True;w.restart.click();return
        if stage==2 and w.live.state=='COMPLETED' and index>=a.qa_frames-1:
            if wait_until is None:wait_until=time.monotonic()+1
            if time.monotonic()<wait_until:return
            w.grab().save(str(folder/'four_views_completed.png'))
            assert any(r['frame']<10 and r['frame']>=0 for r in rows),'Restart did not begin at the first input'
            assert len(w.scene.points)>0 and w.live_cloud.counts()[1]>0
            report=dict(status='PASS',restart_button=True,restarted_from_first_frame=True,
                        last_frame=index,sparse_points=len(w.scene.points),dense_points=w.live_cloud.counts()[1],
                        four_views=True,trajectory_overlay=True,window_size=w.size().toTuple(),session=str(a.metrics.parent))
            (folder/'acceptance.json').write_text(json.dumps(report,indent=2))
            (folder/'completed_restart.json').write_text(json.dumps(dict(session=str(a.metrics.parent),frame=index)))
            done=True;w.restart.click();return
        if stage==3 and index>=30:
            assert any(r['frame']<10 and r['frame']>=0 for r in rows),'Completed run restart skipped first input'
            report=dict(status='PASS',completed_restart=True,first_frame=next(r['frame'] for r in rows if r['frame']>=0),
                        last_frame=index,session=str(a.metrics.parent))
            (folder/'completed_restart_acceptance.json').write_text(json.dumps(report,indent=2))
            done=True;w.close();return
        if time.monotonic()-start>a.exit_after:raise TimeoutError('Actual processing QA deadline')
    except Exception as exc:
        errors.append(str(exc));done=True;w.close()

timer.timeout.connect(sample);timer.start();app.exec()
(folder/('samples_stage%d.json'%stage)).write_text(json.dumps(rows,indent=2))
if errors:
    (folder/'failure.json').write_text(json.dumps(dict(status='FAIL',stage=stage,errors=errors)));raise RuntimeError(str(errors))
