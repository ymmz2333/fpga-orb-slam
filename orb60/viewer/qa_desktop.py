"""Exercise the desktop with a real FPGA/SLAM recording, never fixture poses."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np
from PySide6 import QtWidgets,QtTest
from app import Window


def wait_for(predicate,seconds=20,diagnostic=lambda:''):
    deadline=time.monotonic()+seconds
    while not predicate():
        assert time.monotonic()<deadline,'Desktop condition timed out: '+str(diagnostic())
        QtTest.QTest.qWait(40)
        time.sleep(.005)  # Let the Python decoder run while the Qt test loop is active.


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    app=QtWidgets.QApplication([])
    args=argparse.Namespace(frame_map=None,video=a.video,recording=a.run/'telemetry',connect='')
    window=Window(args);window.show();window.playing=False
    try:
        assert len(window.record.paths)>100
        index=next(i for i,row in enumerate(window.record.timeline) if row['frame_index']>=180)
        window.seek(index)
        diagnostic=lambda:dict(frame=window.current.meta['frame_index'],displayed=window.latest_color_index,
                               decoder_alive=window.color.is_alive(),error=window.color.error,
                               pending=window.color.request,result_token=window.color.result[0] if window.color.result else None)
        wait_for(lambda:window.latest_color_index==window.current.meta['frame_index'],diagnostic=diagnostic)
        meta=window.current.meta;source_index=window.frame_map[meta['timestamp_ns']]
        assert source_index!=meta['frame_index'],'Dataset has a source preroll; test must exercise it'
        cap=cv2.VideoCapture(str(a.video))
        try:
            for _ in range(source_index):assert cap.grab()
            ok,expected=cap.read();assert ok
        finally:cap.release()
        image=window.raw.image;h=image.height();w=image.width();stride=image.bytesPerLine()
        actual=np.frombuffer(image.bits(),np.uint8,count=h*stride).reshape(h,stride)[:,:w*3].reshape(h,w,3)
        np.testing.assert_array_equal(actual,cv2.cvtColor(expected,cv2.COLOR_BGR2RGB))
        for key,item in [('points',window.map_view.cloud),('trajectory',window.map_view.path),
                         ('keyframes',window.map_view.keys),('grid',window.map_view.grid)]:
            window.checks[key].setChecked(False);assert not item.visible()
            window.checks[key].setChecked(True);assert item.visible()
        window.checks['camera'].setChecked(False);assert not window.map_view.camera.visible()
        window.checks['camera'].setChecked(True);assert window.map_view.camera.visible()
        window.follow.setChecked(True);assert window.map_view.follow
        window.follow.setChecked(False);window.map_view.fit(window.scene)
        old=window.index;window.toggle_pause();window.next_due=0;window.tick()
        assert window.index>old;window.toggle_pause();assert not window.playing
        window.seek(0);assert not window.scene.pose_valid and len(window.scene.points)==0
        window.seek(len(window.record.paths)-1);window.map_view.fit(window.scene)
        wait_for(lambda:window.latest_color_index==window.current.meta['frame_index'],diagnostic=diagnostic)
        QtTest.QTest.qWait(500);window.export_snapshot(a.output)
        assert (a.output/'viewer.png').stat().st_size>100000
        ply=(a.output/'map.ply').read_text();assert f'element vertex {len(window.scene.points)}' in ply
        final_points=len(window.scene.points);final_keys=len(window.scene.keyframes)
        before_restart=(window.index,window.playing,len(window.record.paths))
        window.toggle_pause();assert window.index==0 and window.playing,('restart',before_restart,window.index,window.playing)
        window.toggle_pause();assert not window.playing
        result=dict(status='PASS',color_source_mapping_pixel_exact=True,tested_source_frame=source_index,
                    tested_slam_frame=meta['frame_index'],layer_controls=True,play_pause_seek=True,
                    uninitialized_pose_hidden=True,end_replay_restart=True,
                    final_map_points=final_points,final_keyframes=final_keys,snapshot_ply_trajectory_export=True)
        (a.output/'desktop_acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:window.close();app.processEvents()


if __name__=='__main__':main()
