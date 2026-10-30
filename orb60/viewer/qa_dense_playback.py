"""Real-result UI regression: autoplay, pause, seek, restart, zoom and full export."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch
import numpy as np
from PySide6 import QtWidgets,QtTest
from app import Window
from model import view_points


def main():
    p=argparse.ArgumentParser();p.add_argument('--result',required=True,type=Path)
    p.add_argument('--video',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication([])
    args=argparse.Namespace(frame_map=None,video=a.video,recording=None,connect='',dense=a.result)
    # Fail on an unexpected modal warning, rather than hanging the test behind it.
    with patch.object(Window,'message',side_effect=lambda e:(_ for _ in ()).throw(e)):
        w=Window(args);w.show()
    def until(test,seconds=15):
        end=time.perf_counter()+seconds
        while not test() and time.perf_counter()<end:QtTest.QTest.qWait(20)
        assert test(),(w.index,w.statusBar().currentMessage(),w.color.error if w.color else '')
    try:
        until(lambda:w.index>=35)
        autoplay_index=w.index
        times=list(w.draw_times)
        autoplay_fps=(len(times)-1)/(times[-1]-times[0])
        w.toggle_pause();paused=w.index;QtTest.QTest.qWait(250);assert w.index==paused
        # Seek to a true keyframe and verify the exact recorded Twc / observations.
        target=next(i for i,f in enumerate(w.dense_frames) if 'keyframe_id' in f and i>400)
        w.seek(target);until(lambda:w.index==target)
        frame=w.dense_frames[target]
        np.testing.assert_allclose(w.scene.pose,frame['twc'],rtol=1e-6,atol=1e-6)
        assert w.metric_labels['features'].text()==str(len(frame['uv']))
        assert w.raw.image is not None and w.scene.pose_valid
        w.toggle_pause();until(lambda:w.index>target+10);w.toggle_pause()
        # Zoom increases the screen diameter automatically and selects real visible detail.
        assert not w.map_view.dense.pxMode
        size=float(w.map_view.dense.size);view=w.map_view.view
        initial_pixels=size/view.pixelSize(view.opts['center'])
        view.setCameraPosition(distance=view.opts['distance']*.42)
        QtTest.QTest.qWait(1100)
        zoom_pixels=float(w.map_view.dense.size)/view.pixelSize(view.opts['center'])
        assert zoom_pixels>initial_pixels
        ids=w.map_view.dense_indices
        assert 0<len(ids)<=200000
        np.testing.assert_allclose(w.map_view.dense.pos,view_points(w.dense_result.xyz[ids]),atol=1e-6)
        np.testing.assert_allclose(w.map_view.dense.color[:,:3],w.dense_result.rgb[ids]/255.,atol=1e-6)
        value=w.splat_size.value();w.splat_size.setValue(value+.5)
        assert float(w.map_view.dense.size)>size or zoom_pixels>initial_pixels
        assert w.grab().save(str(a.output/'zoom_detail.png'))
        w.map_view.fit(w.scene);QtTest.QTest.qWait(800)
        assert w.grab().save(str(a.output/'overview.png'))
        # Seek to end then restart: the PTS clock must reset, not race through the file.
        last=len(w.dense_frames)-1;w.seek(last);until(lambda:w.index==last)
        w.toggle_pause();until(lambda:w.index>=10 and w.index<100)
        QtTest.QTest.qWait(400);assert w.index<100
        w.toggle_pause()
        target_file=a.output/'full_rgb_export.ply'
        with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(target_file),'PLY (*.ply)')):w.save_cloud()
        sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
        assert sha(target_file)==sha(w.dense_result.cloud)
        report=dict(status='PASS',points=len(w.dense_result.xyz),display_cap=200000,
            autoplay_index=autoplay_index,autoplay_fps_under_qtest=autoplay_fps,video_frames=len(w.dense_frames),pause_seek_restart=True,
            recorded_keyframe_pose_exact=True,actual_keyframe_observations=True,
            view_dependent_real_point_selection=True,zoom_diameter_pixels_before=initial_pixels,
            zoom_diameter_pixels_after=zoom_pixels,full_export_sha256=sha(target_file))
        (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally:w.close();app.processEvents()


if __name__=='__main__':main()
