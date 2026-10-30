"""Both real-data map windows, including GPU readback/presentation and orbit."""
import argparse,json,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PySide6 import QtCore,QtWidgets
from app import Window

p=argparse.ArgumentParser();p.add_argument('result',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
app=QtWidgets.QApplication([])
args=SimpleNamespace(frame_map=None,video=None,recording=None,connect='',dense_live=None,dense=a.result,
                     separate_maps=True,metrics=None,demo_controller=None,buffer_ms=0,processor='RK3588')
window=Window(args);window.show()
timer=QtCore.QTimer();timer.setInterval(16)
views=[window.map_view.view,window.sparse_view.view]
timer.timeout.connect(lambda:[v.setCameraPosition(azimuth=v.opts['azimuth']+.4) for v in views]);timer.start()
def finish():
    try:
        timer.stop();stats=[]
        for name,view in zip(['dense','sparse'],views):
            image=view.grabFramebuffer();assert not image.isNull(),name+' framebuffer missing'
            assert image.save(str(a.output/(name+'.png')))
            image=image.convertToFormat(image.Format.Format_RGBA8888)
            data=np.frombuffer(image.bits(),np.uint8,count=image.sizeInBytes()).reshape(image.height(),image.bytesPerLine())
            rgb=data[:,:image.width()*4].reshape(image.height(),image.width(),4)[:,:,:3]
            assert rgb.std(axis=(0,1)).max()>5,name+' uniform/blank framebuffer'
            status=view.renderer_status();assert status['renderer']=='Mali-G610' and status['paints']>=10,status
            assert not status.get('error'),status
            stats.append(status)
        np.testing.assert_array_equal(window.map_view.cloud.pos,window.sparse_view.cloud.pos)
        np.testing.assert_array_equal(window.map_view.cloud.color,window.sparse_view.cloud.color)
        assert window.map_view.cloud.size==window.sparse_view.cloud.size
        report=dict(status='PASS',scope='Two-window orbit of saved real recording/map; not live tracking FPS',
                    sparse_points=len(window.scene.points),exact_sparse_style=True,views=stats)
        (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    finally:window.close();app.quit()
QtCore.QTimer.singleShot(6000,finish);app.exec()
