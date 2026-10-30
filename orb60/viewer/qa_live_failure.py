"""Observe a real failed startup or interrupted hardware transport; no replay input."""
import argparse,json,time
from pathlib import Path
from PySide6 import QtWidgets,QtCore
from app import Window

p=argparse.ArgumentParser()
for name in ('video','frame-map','metrics','control-file'):p.add_argument('--'+name,type=Path,required=True)
p.add_argument('--dense-live',required=True);p.add_argument('--exit-after',type=float,default=80)
a=p.parse_args();a.connect='';a.recording=None;a.dense=None
app=QtWidgets.QApplication([]);w=Window(a);w.resize(1200,680);w.show()
start=time.monotonic();first_error=None;observed=[];failure=[]
timer=QtCore.QTimer();timer.setInterval(100)
def sample():
    global first_error
    index=w.current.meta['frame_index'] if w.current else None
    if w.live_failure:
        if first_error is None:first_error=time.monotonic()
        observed.append(index)
        if time.monotonic()-first_error>1:
            try:
                assert len(set(observed))==1,'Frames continued after failure'
                assert w.failure_banner.isVisible() and not w.play.isEnabled()
                assert w.raw.image is None and w.feature_image.image is None
                w.grab().save(str(a.metrics.parent/'failure_visible.png'))
                (a.metrics.parent/'failure_acceptance.json').write_text(json.dumps(dict(status='PASS',
                    stopped=True,old_frames_not_played=True,error=w.live_failure,last_frame=index),indent=2))
            except Exception as exc:failure.append(str(exc))
            timer.stop();w.close()
    elif time.monotonic()-start>a.exit_after:
        failure.append('Expected actual failure was not surfaced');timer.stop();w.close()
timer.timeout.connect(sample);timer.start();app.exec()
if failure:raise RuntimeError(str(failure))
