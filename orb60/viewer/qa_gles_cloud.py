"""Time orbit rendering of saved REAL camera/NPU blocks; never a live-input fallback."""
import argparse,json,math,time,os
from pathlib import Path
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets
if os.getenv('ORB60_VIEWER_RENDERER')=='egl-raster':
    import egl_raster_view as gl
else:
    import gles_view as gl
from model import WORLD_TO_VIEW

POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])
p=argparse.ArgumentParser();p.add_argument('chunks',type=Path);p.add_argument('report',type=Path)
p.add_argument('--seconds',type=int,default=8);a=p.parse_args()
gl.configure();app=QtWidgets.QApplication([]);view=gl.GLViewWidget()
view.setWindowTitle('GPU验证 · 已采集彩色点云 · 非实时输入');view.resize(1200,800)
files=sorted(a.chunks.glob('*.json'));budget=max(1,200000//max(1,len(files)));all_points=[];count=0;items=0
for f in files:
    meta=json.loads(f.read_text());raw=f.with_suffix('.bin').read_bytes();points=np.frombuffer(raw,dtype=POINT)
    if len(points)!=meta['points']:raise ValueError('Real point block count mismatch')
    ids=np.linspace(0,len(points)-1,min(len(points),budget),dtype=int)
    selected=points[ids];pose=np.array(meta['twc']);world=selected['xyz']@pose[:3,:3].T+pose[:3,3]
    xyz=world@WORLD_TO_VIEW.T;rgb=selected['rgb'].astype(np.float32)/255.
    view.addItem(gl.GLScatterPlotItem(pos=xyz,color=np.c_[rgb,np.ones(len(rgb))],size=1.5,pxMode=True))
    all_points.append(xyz);count+=len(xyz);items+=1
if not all_points:raise ValueError('No captured NPU blocks; QA refuses synthetic demonstration data')
xyz=np.concatenate(all_points);lo,hi=np.percentile(xyz,[2,98],axis=0);center=(lo+hi)*.5
view.setCameraPosition(pos=QtGui.QVector3D(*map(float,center)),distance=max(.2,float(np.linalg.norm(hi-lo))*1.8))
view.show();timer=QtCore.QTimer();timer.setInterval(16)
timer.timeout.connect(lambda:view.setCameraPosition(azimuth=view.opts['azimuth']+.4));timer.start()
def finish():
    timer.stop();view.grabFramebuffer().save(str(a.report.with_suffix('.png')))
    report=dict(view.renderer_status(),display_points=count,blocks=items,scope='Orbit of saved real camera/NPU points, not live SLAM throughput')
    a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    app.quit()
QtCore.QTimer.singleShot(a.seconds*1000,finish);app.exec()
