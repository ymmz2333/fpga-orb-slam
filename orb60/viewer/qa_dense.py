"""Exercise the real offline reconstruction result in the actual desktop UI."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6 import QtWidgets,QtTest
from app import Window
from model import view_points


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--result',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication([])
    args=argparse.Namespace(frame_map=None,video=None,recording=None,connect='',dense=a.result)
    window=Window(args);window.show()
    try:
        QtTest.QTest.qWait(1200)
        result=window.dense_result
        assert result is not None and len(result.xyz)>=50000
        xyz,rgb=result.sampled()
        assert len(xyz)<=200000
        np.testing.assert_allclose(window.map_view.dense.pos,view_points(xyz),atol=1e-6)
        np.testing.assert_allclose(window.map_view.dense.color[:,:3],rgb/255.,atol=1e-6)
        for name,item in [('dense',window.map_view.dense),('points',window.map_view.cloud)]:
            window.checks[name].setChecked(False);assert not item.visible()
            window.checks[name].setChecked(True);assert item.visible()
        previous=window.map_view.view.opts['azimuth']
        window.map_view.view.orbit(25,12)
        assert window.map_view.view.opts['azimuth']!=previous
        distance=window.map_view.view.opts['distance']
        window.map_view.view.setCameraPosition(distance=distance*.75)
        assert window.map_view.view.opts['distance']<distance
        target=a.output/'exported_full_rgb.ply'
        with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(target),'PLY (*.ply)')):
            window.save_cloud()
        digest=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
        assert digest(target)==digest(result.cloud)
        QtTest.QTest.qWait(700)
        assert window.grab().save(str(a.output/'dense_viewer.png'))
        evidence=dict(status='PASS',real_result=str(a.result.resolve()),points=len(result.xyz),
                      displayed=len(xyz),rgb_exact=True,world_to_view_transform=True,
                      independent_layers=True,rotate_zoom=True,full_rgb_export_sha256=digest(target))
        (a.output/'acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence,indent=2))
    finally:window.close();app.processEvents()


if __name__=='__main__':main()
