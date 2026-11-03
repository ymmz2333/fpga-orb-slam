"""ORB Studio desktop: real FPGA features, camera trajectory and sparse SLAM map."""
import argparse
import csv
import json
import os
os.environ.setdefault('QT_OPENGL','desktop')
from pathlib import Path
import sys
import time
import zlib
from collections import deque
import cv2
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets
if os.getenv('ORB60_VIEWER_RENDERER')=='egl-raster':
    import egl_raster_view as gl
elif os.getenv('ORB60_VIEWER_RENDERER')=='gles':
    import gles_view as gl
elif os.getenv('ORB60_VIEWER_RENDERER')=='desktop':
    import desktop_view as gl
else:
    import pyqtgraph.opengl as gl
from model import Scene,view_points,frustum_lines,export_ply
from sources import LiveSource,Recording,ColorVideo
from dense_result import DenseResult
from dense_playback import RectifyReplay,splat_diameter
from dense_live import DenseLiveSource,LiveChunkLayer,live_point_diameter

TEAL='#43dbc1';MUTED='#8195aa'
STYLE='''
QMainWindow,QWidget {background:#0b121d;color:#dce7f3;font-family:"Microsoft YaHei UI";font-size:12px;}
QFrame#Panel,QFrame#Metric {background:#111d2b;border:1px solid #233448;border-radius:9px;}
QLabel {background:transparent;border:none;}
QLabel#Title {font-size:20px;font-weight:700;color:#f1f6fb;}
QLabel#Section {font-weight:600;font-size:13px;color:#f1f6fb;}
QLabel#Sub {font-size:11px;color:#8195aa;}
QLabel#Value {font-size:25px;font-weight:600;color:#43dbc1;}
QPushButton {background:#1a2b3e;border:1px solid #30455c;border-radius:6px;padding:8px 13px;color:#dce7f3;}
QPushButton:hover {background:#25405a;border-color:#43dbc1;}
QPushButton:checked {background:#194239;border-color:#43dbc1;color:#7bf3d6;}
QPushButton#Primary {background:#35cdb2;border:none;color:#061f21;font-weight:700;}
QPushButton:disabled {color:#52687d;background:#14202f;}
QLineEdit,QComboBox {background:#101c2a;border:1px solid #30455c;border-radius:6px;padding:7px;}
QCheckBox {spacing:8px;background:transparent;padding:4px 0;}
QCheckBox::indicator {width:14px;height:14px;}
QSlider::groove:horizontal {height:4px;background:#263b51;border-radius:2px;}
QSlider::handle:horizontal {width:12px;background:#43dbc1;margin:-5px 0;border-radius:6px;}
QStatusBar {background:#101b29;color:#8195aa;}
QSplitter::handle {background:#0b121d;}
'''


class ImageView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__();self.image=None;self.setMinimumSize(120,80)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,QtWidgets.QSizePolicy.Policy.Expanding)
    def image_rect(self):
        size=(self.image.size() if self.image is not None else QtCore.QSize(960,720)).scaled(self.size(),QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        return QtCore.QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())
    def set_image(self,image):
        image=cv2.cvtColor(image,cv2.COLOR_GRAY2RGB) if image.ndim==2 else cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        h,w=image.shape[:2];self.image=QtGui.QImage(image.data,w,h,image.strides[0],QtGui.QImage.Format.Format_RGB888).copy();self.update()
    def paintEvent(self,event):
        painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor('#070d16'))
        if self.image is not None:
            target=self.image_rect()
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform);painter.drawImage(target,self.image)
        else:
            painter.setPen(QtGui.QColor(MUTED));painter.drawText(self.rect(),QtCore.Qt.AlignmentFlag.AlignCenter,'等待真实图像输入')


class SafeLine(gl.GLLinePlotItem):
    def paint(self):
        # Empty GL line buffers can crash the Windows driver; there is no line to draw.
        if self.pos is None or not len(self.pos):return
        super().paint()


def panel(title,subtitle=''):
    box=QtWidgets.QFrame();box.setObjectName('Panel');layout=QtWidgets.QVBoxLayout(box);layout.setContentsMargins(13,12,13,12);layout.setSpacing(8)
    row=QtWidgets.QHBoxLayout();name=QtWidgets.QLabel(title);name.setObjectName('Section');row.addWidget(name);row.addStretch()
    hint=QtWidgets.QLabel(subtitle);hint.setObjectName('Sub');row.addWidget(hint);layout.addLayout(row)
    return box,layout,hint


class MapView(QtWidgets.QWidget):
    dense_lod_changed=QtCore.Signal()
    def __init__(self):
        super().__init__();layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.view=gl.GLViewWidget();self.view.setBackgroundColor('#0a1421');layout.addWidget(self.view)
        self.view.setCameraPosition(distance=8,elevation=25,azimuth=-60)
        self.grid=gl.GLGridItem();self.grid.setSize(10,10);self.grid.setSpacing(1,1);self.grid.setColor((52,78,101,100));self.view.addItem(self.grid)
        self.axes=gl.GLAxisItem();self.axes.setSize(1,1,1);self.view.addItem(self.axes)
        self.cloud=gl.GLScatterPlotItem(pos=np.empty((0,3)),size=2.5,color=(.24,.78,.84,.9),pxMode=True)
        self.dense=gl.GLScatterPlotItem(pos=np.empty((0,3)),size=1.6,color=(1,1,1,1),pxMode=True,glOptions='opaque')
        self.dense_points=np.empty((0,3),np.float32)
        self.path=SafeLine(pos=np.empty((0,3)),mode='lines',color=(.28,.94,.77,1),width=2,antialias=True)
        self.keys=SafeLine(pos=np.empty((0,3)),mode='lines',color=(.85,.65,.30,.65),width=1,antialias=True)
        self.camera=SafeLine(pos=np.empty((0,3)),mode='lines',color=(.4,1,.74,1),width=2,antialias=True)
        for item in (self.cloud,self.dense,self.path,self.keys,self.camera):self.view.addItem(item)
        self.set_trajectory_overlay(True)
        self.follow=False;self.show_camera=True;self.scale=.1;self.fit_map=None;self.cloud_source=None;self.keys_source=None
        self.lod_source=None;self.lod_signature=None;self.lod_pending=None
        self.auto_fit_enabled=True;self.last_fit=0.;self.fit_source=None
        self.view.installEventFilter(self)
        if hasattr(self.view,'interacted'):
            self.view.interacted.connect(lambda:setattr(self,'auto_fit_enabled',False))
        self.lod_timer=QtCore.QTimer(self);self.lod_timer.timeout.connect(self.refresh_dense_lod);self.lod_timer.start(250)

    def eventFilter(self,obj,event):
        if obj is self.view and event.type() in (QtCore.QEvent.Type.MouseButtonPress,QtCore.QEvent.Type.Wheel):
            self.auto_fit_enabled=False
        return super().eventFilter(obj,event)

    def auto_fit(self,scene):
        source=self.dense_points if len(self.dense_points) else scene.points
        if self.auto_fit_enabled and source is not self.fit_source and time.perf_counter()-self.last_fit>1:
            self.fit(scene)

    def copy_sparse_points(self,source):
        # Both windows render the exact same sparse point array. Only view and
        # display size differ; no dense samples or second map are substituted.
        points=source.cloud.pos
        if points is None:points=np.empty((0,3),np.float32)
        if getattr(self,'shared_sparse_source',None) is not points:
            self.cloud.setData(pos=points,color=source.cloud.color,size=source.cloud.size,pxMode=source.cloud.pxMode)
            self.shared_sparse_source=points
        self.cloud.setVisible(True)

    def set_trajectory_overlay(self,enabled):
        # Draw after opaque points, without changing any SLAM coordinates.
        from OpenGL.GL import GL_DEPTH_TEST,GL_BLEND,GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA
        for item in (self.path,self.camera):
            item.setDepthValue(100 if enabled else 0)
            item.setGLOptions({GL_DEPTH_TEST:not enabled,GL_BLEND:True,
                               'glBlendFunc':(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)})

    def set_dense_source(self,result):
        self.lod_source=result;self.lod_signature=None;self.lod_pending=None
        if result is None:
            self.dense_all_view=np.empty((0,3),np.float32);return
        self.dense_all_view=view_points(result.xyz);self.dense_indices=result.indices
        self.dense_visible_count=len(result.xyz)

    def refresh_dense_lod(self):
        source=self.lod_source
        if source is None or not hasattr(self,'dense_fit_distance'):return
        o=self.view.opts;c=o['center']
        signature=(o['distance'],o['elevation'],o['azimuth'],c.x(),c.y(),c.z(),self.view.width(),self.view.height())
        if signature==self.lod_signature:return
        if signature!=self.lod_pending:self.lod_pending=signature;return
        self.lod_signature=signature
        if o['distance']>=self.dense_fit_distance*.75:
            indices=source.indices;count=len(source.xyz)
        else:
            viewport=self.view.getViewport()
            matrix=self.view.projectionMatrix(viewport,viewport)*self.view.viewMatrix()
            m=np.array(matrix.data(),np.float32).reshape(4,4).T
            clip=self.dense_all_view@m[:,:3].T+m[:,3]
            w=clip[:,3];counted=(w>0)&(np.abs(clip[:,0])<w*1.03)&(np.abs(clip[:,1])<w*1.03)&(np.abs(clip[:,2])<w)
            indices=np.flatnonzero(counted);count=len(indices)
            if count>200000:indices=np.sort(np.random.RandomState(1729).choice(indices,200000,replace=False))
        self.dense_indices=indices;self.dense_visible_count=count
        rgb=source.rgb[indices].astype(np.float32)/255.
        self.dense.setData(pos=self.dense_all_view[indices],color=np.c_[rgb,np.ones(len(indices),np.float32)])
        self.dense_lod_changed.emit()

    def update_scene(self,scene):
        points=view_points(scene.points)
        if self.cloud_source is not scene.points and len(points):
            lo,hi=np.percentile(points[:,2],[5,95]);values=np.clip((points[:,2]-lo)/max(float(hi-lo),1e-6),0,1)
            colors=np.column_stack((.18+.55*values,.48+.40*values,.82-.28*values,np.full(len(points),.9)))
            self.cloud.setData(pos=points,color=colors)
        elif not len(points):self.cloud.setData(pos=np.empty((0,3)))
        self.cloud_source=scene.points
        if getattr(self,'raw_sparse',False):self.cloud.setVisible(True)
        self.path.setData(pos=view_points(np.array(scene.segments).reshape(-1,3)))
        if self.keys_source is not scene.keyframes:
            self.keys.setData(pos=frustum_lines(scene.keyframes[-400:],self.scale*.55));self.keys_source=scene.keyframes
        self.camera.setData(pos=frustum_lines(scene.pose[None,:,:],self.scale))
        self.camera.setVisible(self.show_camera and scene.pose_valid)
        if self.fit_map!=scene.map_id and len(points)>10:self.fit(scene);self.fit_map=scene.map_id
        self.auto_fit(scene)
        if self.follow and scene.pose_valid:
            p=view_points(scene.pose[:3,3]);self.view.setCameraPosition(pos=QtGui.QVector3D(*map(float,p)))

    def fit(self,scene):
        source=self.dense_points if len(self.dense_points) else scene.points
        if not len(source):return
        points=view_points(source);lo,hi=np.percentile(points,[2,98],axis=0)
        if scene.segments and not getattr(self,'raw_sparse',False):
            trace=view_points(np.array(scene.segments).reshape(-1,3));lo=np.minimum(lo,trace.min(axis=0));hi=np.maximum(hi,trace.max(axis=0))
        center=(lo+hi)/2;radius=max(float(np.linalg.norm(hi-lo))/2,.2);self.scale=radius*.045
        half=np.deg2rad(self.view.opts['fov']/2)
        vertical=np.arctan(np.tan(half)*max(1,self.view.height())/max(1,self.view.width()))
        corners=np.array([[x,y,z] for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])])
        rotation=np.array(self.view.viewMatrix().data()).reshape(4,4).T[:3,:3]
        camera=(corners-center)@rotation.T
        distance=max(.1,float(np.max(camera[:,2]+1.12*np.maximum(np.abs(camera[:,0])/np.tan(half),
                                                                     np.abs(camera[:,1])/np.tan(vertical)))))
        if getattr(self,'raw_sparse',False):distance=max(.1,radius*4)
        self.view.setCameraPosition(pos=QtGui.QVector3D(*map(float,center)),distance=float(distance))
        self.dense_fit_distance=distance;self.last_fit=time.perf_counter();self.fit_source=source
        extent=max(1.,float(2**np.ceil(np.log2(radius*2))))
        self.grid.setSize(extent*2,extent*2);self.grid.setSpacing(extent/10,extent/10)
        self.axes.setSize(radius*.3,radius*.3,radius*.3)
        self.keys.setData(pos=frustum_lines(scene.keyframes[-400:],self.scale*.55))
        self.camera.setData(pos=frustum_lines(scene.pose[None,:,:],self.scale))


class Window(QtWidgets.QMainWindow):
    def __init__(self,args):
        super().__init__();self.setWindowTitle('ORB Studio · FPGA SLAM 上位机');self.scene=Scene();self.live=None;self.record=None;self.color=None
        self.current=None;self.index=-1;self.playing=False;self.paused=False;self.next_due=0.;self.latest_color_index=-1
        self.frame_map={};self.frame_map_path=None
        self.pending_live=None;self.draw_times=deque(maxlen=3000);self.draw_costs=deque(maxlen=3000)
        self.connection_history=[];self.draw_frames=deque(maxlen=3000)
        self.dense_result=None
        self.live_cloud=None
        self.pending_since=0.;self.live_failure=None;self.last_diagnostic=0.
        self.dense_frames=[];self.dense_seek_pending=False;self.dense_video=None
        if args.frame_map:self.load_frame_map(args.frame_map)
        self.displayed=0;self.display_start=time.perf_counter();self.last_frame=0.;self.args=args
        self.build();self.setStyleSheet(STYLE)
        geometry=QtWidgets.QApplication.primaryScreen().availableGeometry()
        # Disconnected RK HDMI reports an empty QScreen work area although X11
        # still has a framebuffer. Keep test/remote windows within that framebuffer.
        if geometry.width()<640 or geometry.height()<480:geometry=QtCore.QRect(0,0,1024,768)
        self.resize(min(1500,geometry.width()-24),min(900,geometry.height()-36))
        self.move(geometry.x()+12,geometry.y()+12)
        if getattr(args,'separate_maps',False) and hasattr(self.map_view.view,'detach'):
            main_width=min(840,int(geometry.width()*.43));self.resize(main_width,min(1000,geometry.height()-50))
            x=geometry.x()+main_width+30;y=geometry.y()+40
            w=min(1100,geometry.width()-main_width-50);h=min(700,(geometry.height()-95)//2)
            self.map_view.view.detach('彩色稠密点云 · 左键旋转 / 滚轮缩放',QtCore.QRect(x,y,w,h))
            self.sparse_view.view.detach('原始稀疏地图 · 左键旋转 / 滚轮缩放',QtCore.QRect(x,y+h+35,w,h))
        self.timer=QtCore.QTimer(self);self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer);self.timer.timeout.connect(self.tick);self.timer.start(16)
        if args.video:self.open_video(args.video)
        if args.recording:self.open_record(args.recording)
        if args.connect:self.endpoint.setText(args.connect);self.connect_live()
        if getattr(args,'dense_live',None):self.endpoint.setText(args.dense_live);self.connect_dense_live()
        if getattr(args,'dense',None):self.open_dense(args.dense)

    def build(self):
        central=QtWidgets.QWidget();self.setCentralWidget(central);root=QtWidgets.QVBoxLayout(central);root.setContentsMargins(10,8,10,6);root.setSpacing(6)
        header=QtWidgets.QHBoxLayout();logo=QtWidgets.QLabel('◈');logo.setStyleSheet('font-size:30px;color:#43dbc1');header.addWidget(logo)
        title=QtWidgets.QVBoxLayout();label=QtWidgets.QLabel('ORB STUDIO');label.setObjectName('Title');title.addWidget(label)
        subtitle=QtWidgets.QLabel('FPGA ORB  /  VISUAL SLAM');subtitle.setObjectName('Sub');title.addWidget(subtitle);header.addLayout(title);header.addStretch()
        self.mode=QtWidgets.QLabel('离线 / 尚未连接');self.mode.setStyleSheet('color:#e4bf78;padding:7px 12px;background:#24303a;border-radius:5px');header.addWidget(self.mode)
        self.endpoint=QtWidgets.QLineEdit();self.endpoint.setPlaceholderText('SSH 隧道 127.0.0.1:18765');self.endpoint.setFixedWidth(210);header.addWidget(self.endpoint)
        self.connect_button=QtWidgets.QPushButton('连接设备');self.connect_button.setObjectName('Primary');self.connect_button.clicked.connect(self.reconnect_source);header.addWidget(self.connect_button)
        self.restart=QtWidgets.QPushButton('重新开始');self.restart.clicked.connect(self.restart_processing);header.addWidget(self.restart)
        self.restart.setEnabled(bool(getattr(self.args,'control_file',None)))
        button=QtWidgets.QPushButton('打开记录');button.clicked.connect(lambda:self.choose_record());header.addWidget(button)
        dense_button=QtWidgets.QPushButton('打开建模结果');dense_button.clicked.connect(self.choose_dense);header.addWidget(dense_button)
        if getattr(self.args,'dense_live',None):
            button.hide();dense_button.hide();self.endpoint.hide();self.connect_button.hide()
        root.addLayout(header)
        if getattr(self.args,'demo_controller',None):
            from demo_controls import DemoControls
            self.demo_controls=DemoControls(self.args.demo_controller,self)
            self.demo_run=None
            self.endpoint.hide();self.connect_button.setText('启动摄像头建图')
            self.demo_controls.updated.connect(self.demo_status)
            self.demo_controls.failed.connect(lambda reason:self.demo_display_stopped('控制连接中断；本地运行状态请看 HDMI'))
            root.addWidget(self.demo_controls)
        self.failure_banner=QtWidgets.QLabel();self.failure_banner.setWordWrap(True)
        self.failure_banner.setStyleSheet('background:#50232b;color:#ffd9d9;padding:8px;border-radius:5px;')
        self.failure_banner.hide();root.addWidget(self.failure_banner)
        body=QtWidgets.QHBoxLayout();body.setSpacing(12);root.addLayout(body,1)
        sidebar=QtWidgets.QWidget();side=QtWidgets.QVBoxLayout(sidebar);side.setContentsMargins(0,0,4,0);side.setSpacing(6)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(sidebar);scroll.setFixedWidth(204)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame);scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(scroll)
        device,layout,_=panel('系统组成');side.addWidget(device)
        processor=getattr(self.args,'processor','RK3588')
        for name,detail in (('●  ZYNQ FPGA','ORB 特征 / 150 MHz'),('●  '+processor,'SLAM / 地图优化'),('●  DESKTOP','可视化 / 只读显示')):
            label=QtWidgets.QLabel(name);label.setStyleSheet('font-weight:600;color:#65dbca;padding-top:6px');layout.addWidget(label)
            label=QtWidgets.QLabel(detail);label.setObjectName('Sub');layout.addWidget(label)
        self.metric_labels={};self.metric_names={}
        for key,name,unit in (('fps','SLAM 处理速度','FPS'),('features','当前特征','POINTS'),('map','三维地图点','LANDMARKS')):
            box=QtWidgets.QFrame();box.setObjectName('Metric');v=QtWidgets.QVBoxLayout(box);label=QtWidgets.QLabel(name);label.setObjectName('Sub');v.addWidget(label)
            self.metric_names[key]=label
            row=QtWidgets.QHBoxLayout();value=QtWidgets.QLabel('—');value.setObjectName('Value');row.addWidget(value);small=QtWidgets.QLabel(unit);small.setObjectName('Sub');row.addWidget(small);row.addStretch();v.addLayout(row);self.metric_labels[key]=value;side.addWidget(box)
        controls,layout,_=panel('图层与视角');side.addWidget(controls)
        self.checks={}
        for key,name in (('points','稀疏地图点'),('dense','彩色稠密点云'),('trajectory','相机轨迹'),('keyframes','关键帧'),('camera','当前相机'),('grid','参考网格')):
            check=QtWidgets.QCheckBox(name);check.setChecked(True);check.toggled.connect(lambda value,k=key:self.layer(k,value));layout.addWidget(check);self.checks[key]=check
        self.follow=QtWidgets.QCheckBox('跟随相机');self.follow.toggled.connect(lambda x:setattr(self.map_view,'follow',x));layout.addWidget(self.follow)
        self.trajectory_overlay=QtWidgets.QCheckBox('轨迹置顶');self.trajectory_overlay.setChecked(True)
        self.trajectory_overlay.toggled.connect(self.set_trajectory_overlay);layout.addWidget(self.trajectory_overlay)
        self.splat_auto=QtWidgets.QCheckBox('点大小随缩放调整');self.splat_auto.setChecked(True)
        self.splat_auto.toggled.connect(self.update_dense_size);layout.addWidget(self.splat_auto)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('点大小'))
        self.splat_size=QtWidgets.QDoubleSpinBox();self.splat_size.setRange(.2,5);self.splat_size.setSingleStep(.1);self.splat_size.setValue(1.0)
        self.splat_size.valueChanged.connect(self.update_dense_size);row.addWidget(self.splat_size);layout.addLayout(row)
        reset=QtWidgets.QPushButton('适配地图  F');reset.clicked.connect(self.fit_maps);layout.addWidget(reset)
        export=QtWidgets.QPushButton('导出点云 PLY');export.clicked.connect(self.save_cloud);layout.addWidget(export)
        self.info=QtWidgets.QLabel('单目地图 · 相对尺度\n显示坐标 X / Z / −Y\n不包含飞行控制');self.info.setObjectName('Sub');self.info.setWordWrap(True);side.addWidget(self.info);side.addStretch()
        split=QtWidgets.QSplitter();self.main_split=split;body.addWidget(split,1)
        video=QtWidgets.QWidget();videos=QtWidgets.QVBoxLayout(video);videos.setContentsMargins(0,0,0,0);videos.setSpacing(12)
        raw,layout,self.raw_hint=panel('01  当前输入','等待输入');self.raw_hint.setWordWrap(True);self.raw_hint.setMaximumWidth(220)
        self.raw=ImageView();layout.addWidget(self.raw,1);videos.addWidget(raw,1)
        features,layout,self.feature_hint=panel('02  灰度 / FPGA 特征','绿色：地图关联   金色：未关联')
        self.feature_hint.setWordWrap(True);self.feature_hint.setMaximumWidth(220)
        self.feature_image=ImageView();layout.addWidget(self.feature_image,1);videos.addWidget(features,1);split.addWidget(video)
        mapping,layout,self.map_hint=panel('03  三维地图','SLAM 稀疏重建');self.map_view=MapView();layout.addWidget(self.map_view,1)
        self.map_view.dense_lod_changed.connect(self.update_dense_size)
        footer=QtWidgets.QHBoxLayout();self.pose_text=QtWidgets.QLabel('尚未初始化 · 无有效位姿');self.pose_text.setObjectName('Sub');footer.addWidget(self.pose_text);footer.addStretch()
        self.state_text=QtWidgets.QLabel('WAITING');self.state_text.setStyleSheet('color:#efbf70');footer.addWidget(self.state_text);layout.addLayout(footer)
        self.map_hint.setWordWrap(True);self.map_hint.setMaximumWidth(330)
        self.pose_text.setWordWrap(True)
        help_text=QtWidgets.QLabel('左键旋转 · 中键平移 · 滚轮缩放 · F 适配');help_text.setObjectName('Sub');layout.addWidget(help_text)
        maps=QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical);maps.setChildrenCollapsible(False);maps.addWidget(mapping)
        sparse,sp,self.sparse_hint=panel('04  原始点云地图','当前 SLAM 稀疏观测 · 实时更新')
        self.sparse_hint.setWordWrap(True);self.sparse_hint.setMaximumWidth(260)
        self.sparse_view=MapView();self.sparse_view.raw_sparse=True
        sp.addWidget(self.sparse_view,1);maps.addWidget(sparse);maps.setSizes([400,300])
        self.detached_map_panels=maps
        if getattr(self.args,'separate_maps',False):maps.hide()
        else:split.addWidget(maps)
        split.setChildrenCollapsible(False);split.setSizes([390,720]);split.setStretchFactor(0,0)
        if not getattr(self.args,'separate_maps',False):split.setStretchFactor(1,1)
        playback=QtWidgets.QHBoxLayout();self.play=QtWidgets.QPushButton('播放 / 暂停');self.play.clicked.connect(self.toggle_pause);playback.addWidget(self.play)
        self.slider=QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal);self.slider.setRange(0,0);self.slider.sliderReleased.connect(lambda:self.seek(self.slider.value()));playback.addWidget(self.slider,1)
        self.frame_text=QtWidgets.QLabel('FRAME —');playback.addWidget(self.frame_text)
        self.speed=QtWidgets.QComboBox();self.speed.addItems(['0.5×','1×','2×']);self.speed.setCurrentIndex(1);playback.addWidget(self.speed)
        color=QtWidgets.QPushButton('选择彩色原片');color.clicked.connect(self.choose_video);playback.addWidget(color)
        if getattr(self.args,'dense_live',None):color.hide();self.speed.hide();self.slider.hide()
        screenshot=QtWidgets.QPushButton('保存快照');screenshot.clicked.connect(self.save_snapshot);playback.addWidget(screenshot);root.addLayout(playback)
        self.statusBar().showMessage('连接鲁班猫可视化服务，或打开 .orbv 记录目录。仅显示真实观测，不生成模拟地图。')
        self.fit_shortcut=QtGui.QShortcut(QtGui.QKeySequence('F'),self);self.fit_shortcut.activated.connect(self.fit_maps)

    def fit_maps(self):
        self.map_view.auto_fit_enabled=True;self.sparse_view.auto_fit_enabled=True
        self.map_view.fit(self.scene);self.sparse_view.fit(self.scene)

    def set_trajectory_overlay(self,value):
        self.map_view.set_trajectory_overlay(value);self.sparse_view.set_trajectory_overlay(value)

    def layer(self,key,value):
        items=dict(points=self.map_view.cloud,dense=self.map_view.dense,trajectory=self.map_view.path,keyframes=self.map_view.keys,grid=self.map_view.grid)
        if key=='camera':self.map_view.show_camera=value;self.map_view.camera.setVisible(value and self.scene.pose_valid)
        else:items[key].setVisible(value)
        if key=='dense' and self.live_cloud:self.live_cloud.set_visible(value)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'main_split'):
            # Two 4:3 images should fit the available height, instead of imposing
            # the old tall sidebar's minimum height on the whole main window.
            width=max(240,min(500,int(max(180,self.height()-235)*2/3)))
            self.main_split.setSizes([width,max(300,self.main_split.width()-width)])

    def connect_dense_live(self):
        try:
            self.clear_dense()
            if self.live:self.live.close()
            host,port=self.endpoint.text().strip().rsplit(':',1)
            self.live=DenseLiveSource(host,int(port));self.live.start();self.record=None;self.playing=False;self.paused=False
            self.live_cloud=LiveChunkLayer(self.map_view)
            self.dense_generation=0;self.live_failure=None;self.failure_banner.hide()
            self.scene.reset();self.slider.setRange(0,0);self.pending_live=None
            self.slider.setEnabled(False);self.speed.setEnabled(False);self.play.setText('暂停显示')
            self.mode.setText('实时处理 · 等待关键帧');self.checks['dense'].setChecked(True)
            self.raw_hint.setText('等待SLAM启动 · 正在加载词典 / 初始化')
            self.checks['keyframes'].setChecked(False);self.checks['points'].setChecked(False)
            self.statusBar().showMessage('实际 FPGA 特征 + SLAM 跟踪 + NPU 深度；每个关键帧追加一个点块，视频帧只更新相机。')
        except Exception as exc:self.message(exc)

    def control(self,action,reason=''):
        path=getattr(self.args,'control_file',None)
        if path:
            path=Path(path);tmp=path.with_suffix('.tmp')
            tmp.write_text(json.dumps(dict(action=action,reason=reason)),encoding='utf-8');tmp.replace(path)

    def demo_display_stopped(self,label):
        if self.live:self.live.close();self.live=None
        self.pending_live=None;self.current=None;self.scene.pose_valid=False
        self.map_view.camera.setVisible(False);self.sparse_view.camera.setVisible(False)
        self.raw.image=None;self.raw.update();self.feature_image.image=None;self.feature_image.update()
        self.mode.setText(label);self.state_text.setText('无当前 RK 位姿 · '+label)
        self.pose_text.setText('无当前 RK 位姿；独立定位以 Zynq HDMI 为准')
        self.metric_labels['fps'].setText('—');self.metric_labels['features'].setText('—')

    def demo_status(self,value):
        state=value.get('state');run=value.get('run')
        self.connect_button.setToolTip('FPGA '+value.get('zynq_host','未知')+'；预览由 RK 控制器选择，不使用旧手动地址')
        self.connect_button.setText('重连预览' if state=='MAPPING' else '启动摄像头建图')
        self.connect_button.setEnabled(not value.get('busy',False) and bool(value.get('zynq',{}).get('hardware_verified')) and not value.get('zynq',{}).get('hardware_fault',False))
        if state=='MAPPING' and run and run!=self.demo_run:
            from urllib.parse import urlparse
            host=urlparse(self.args.demo_controller).hostname
            dense=value.get('dense_enabled',False)
            self.endpoint.setText(f"{host}:{value.get('dense_port',18786) if dense else value.get('viewer_port',18765)}")
            self.demo_run=run;self.live_failure=None
            if dense:self.connect_dense_live()
            else:self.connect_live()
        elif state in ('LOCAL','LOCAL_RELOCALIZING','ERROR','STOPPED'):
            self.demo_display_stopped('Zynq 独立定位，请看 HDMI' if state in ('LOCAL','LOCAL_RELOCALIZING') else '处理已停止')
            if state in ('LOCAL','LOCAL_RELOCALIZING') and run and getattr(self,'saved_map_run',None)!=run and Path(run).is_dir():
                self.restore_saved_demo_map(Path(run),value.get('zynq',{}).get('map_id'))
        elif state in ('FINALIZING','INSTALLING'):
            self.demo_display_stopped('建图收尾／地图安装中，暂无当前 RK 位姿')

    def restore_saved_demo_map(self,run,mid):
        import csv
        folder=run/'tracking/map_for_zynq'
        if not folder.is_dir():return
        with (folder/'points.csv').open() as f:points=list(csv.DictReader(f))
        with (folder/'keyframes.csv').open() as f:keys=list(csv.DictReader(f))
        self.scene.reset();self.scene.map_id=int(mid)
        self.scene.points=np.array([[float(p[k]) for k in ('x','y','z')] for p in points],np.float32).reshape(-1,3)
        self.scene.point_ids=np.array([int(p['point_id']) for p in points],np.uint64)
        self.scene.keyframes=np.array([[[float(k['twc_%d%d'%(r,c)]) for c in range(4)] for r in range(4)] for k in keys],np.float32).reshape(-1,4,4)
        for a,b in zip(self.scene.keyframes[:-1],self.scene.keyframes[1:]):self.scene.segments.extend((a[:3,3],b[:3,3]))
        self.clear_dense();self.live_cloud=None
        from dense_live import POINT
        environment=folder/'dense_environment.bin'
        if environment.is_file():
            import hashlib,struct
            data=environment.read_bytes();manifest={line.split()[2]:line.split()[0] for line in (folder/'manifest.txt').read_text().splitlines()[1:]}
            if hashlib.sha256(data).hexdigest()!=manifest.get('dense_environment.bin'):raise ValueError('稠密交接文件 SHA 不匹配')
            if len(data)<144 or data[:8]!=b'ORBDNS01':raise ValueError('稠密环境格式错误')
            count=struct.unpack_from('<I',data,8)[0]
            if not 1<=count<=2000000 or len(data)!=144+count*POINT.itemsize:raise ValueError('稠密环境容量错误')
            cloud=np.frombuffer(data,POINT,offset=144);ids=np.linspace(0,count-1,min(count,40000),dtype=int)
            self.map_view.dense_points=cloud['xyz'].copy()
            self.map_view.dense.setData(pos=view_points(cloud['xyz'][ids]),color=np.c_[cloud['rgb'][ids].astype(np.float32)/255.,np.ones(len(ids))])
        else:
            self.live_cloud=LiveChunkLayer(self.map_view);self.live_cloud.select_map(int(mid))
            for f in sorted((run/'dense/chunks').glob('*.json')):
                meta=json.loads(f.read_text())
                if int(meta['map_id'])!=int(mid):continue
                data=f.with_suffix('.bin').read_bytes()
                if len(data)!=int(meta['points'])*POINT.itemsize:raise ValueError('已保存彩色点块长度不匹配')
                self.live_cloud.add(meta,np.frombuffer(data,dtype=POINT).copy())
            self.live_cloud.select_map(int(mid));self.live_cloud.update_fit_points()
        self.map_view.update_scene(self.scene);self.sparse_view.update_scene(self.scene)
        self.sparse_view.copy_sparse_points(self.map_view);self.fit_maps()
        self.checks['dense'].setChecked(True)
        self.saved_map_run=str(run);self.info.setText('已保存地图 · 可旋转缩放\n当前 Zynq 独立定位请看 HDMI\n本窗口没有播放旧视频或旧位姿')

    def restart_processing(self):
        if not getattr(self.args,'control_file',None):return
        self.restart.setEnabled(False);self.control('restart');self.close()

    def fail_live(self,reason):
        if self.live_failure:return
        self.live_failure=str(reason);self.pending_live=None;self.paused=True
        self.play.setEnabled(False);self.control('stop',self.live_failure)
        self.failure_banner.setText('处理已停止：'+self.live_failure[:400]+'\n连接恢复后点击“重新开始”，将从首帧重新执行 FPGA 加速。')
        self.failure_banner.setToolTip(self.live_failure)
        self.failure_banner.show();self.mode.setText('处理失败 · 已停止')
        self.raw.image=None;self.raw.update();self.feature_image.image=None;self.feature_image.update()
        self.map_view.camera.setVisible(False);self.sparse_view.camera.setVisible(False);self.state_text.setText('STOPPED · 最后有效地图')
        self.statusBar().showMessage(self.live_failure)

    def reconnect_source(self):
        if getattr(self.args,'demo_controller',None):
            self.demo_run=None
            self.demo_controls.request('start_mapping')
            return
        if self.live_cloud or getattr(self.args,'dense_live',None):self.connect_dense_live()
        else:self.connect_live()

    def connect_live(self):
        try:
            self.clear_dense()
            value=self.endpoint.text().strip();host,port=value.rsplit(':',1) if ':' in value else (value,'8765')
            if not host:raise ValueError('请输入鲁班猫地址')
            if self.live:
                self.live.close();self.connection_history.append(dict(received=self.live.received,replaced=self.live.replaced))
            self.live=LiveSource(host,int(port),getattr(self.args,'buffer_ms',0));self.live.start();self.record=None;self.playing=False;self.paused=False
            self.scene.reset();self.slider.setRange(0,0);self.mode.setText('连接中');self.statusBar().showMessage('正在连接只读可视化服务…')
            self.pending_live=None
        except Exception as exc:self.message(exc)

    def choose_record(self):
        name=QtWidgets.QFileDialog.getExistingDirectory(self,'选择包含 frames/*.orbv 的记录目录')
        if name:self.open_record(name)

    def open_record(self,path):
        try:
            record=Recording(path)
            self.clear_dense()
            if self.live:self.live.close();self.live=None
            self.record=record;self.slider.setRange(0,len(record.paths)-1);self.scene.reset();self.paused=False;self.playing=True
            self.frame_map={};self.frame_map_path=None
            for candidate in (self.args.frame_map,Path(path)/'source_frames.csv',Path(path).parent/'source_frames.csv'):
                if candidate is None:continue
                if candidate.is_file():self.load_frame_map(candidate);break
            self.mode.setText('记录回放');self.seek(0);self.statusBar().showMessage(f'已打开 {len(record.paths)} 个真实显示快照；按原始输入时间戳回放。')
        except Exception as exc:self.message(exc)

    def seek(self,index):
        if self.dense_result and self.dense_frames:
            self.seek_dense(index);return
        if not self.record:return
        self.scene.reset();map_frame=self.record.nearest_map(index)
        if map_frame:
            self.scene.map_id=map_frame.meta['map_id'];self.scene.points=map_frame.points['xyz'].copy()
            self.scene.point_ids=map_frame.points['id'].copy();self.scene.keyframes=map_frame.keyframes['twc'].copy()
        # Retain only this map's trajectory. Replay metadata is bounded, no image cache.
        previous=None
        for meta in self.record.timeline[:index]:
            if meta['map_id']!=self.scene.map_id:continue
            if meta['pose_valid'] and meta['state']==2:
                pose=np.array(meta['pose_twc'],dtype=np.float32).reshape(4,4);self.scene.trace.append((meta['timestamp_ns'],pose));p=pose[:3,3]
                if previous is not None:self.scene.segments.extend((previous,p))
                previous=p
            else:previous=None
        self.scene.previous_valid=previous is not None;self.scene.last_position=previous
        self.index=index;self.show_snapshot(self.record.read(index));self.slider.setValue(index);self.next_due=time.perf_counter()+.1

    def choose_video(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'选择同一序列的原始彩色视频','','Video (*.mp4 *.mkv *.avi)')
        if path:self.open_video(path)

    def open_video(self,path):
        if self.dense_result and self.dense_result.replay:
            try:
                self.start_dense_replay(path)
            except Exception as exc:self.message(exc)
            return
        if self.color:self.color.close()
        self.color=ColorVideo(path,exact_gray=bool(getattr(self.args,'dense_live',None)));self.color.start();self.latest_color_index=-1
        if self.current:self.request_color(self.current.meta)

    def load_frame_map(self,path):
        with Path(path).open() as f:
            self.frame_map={int(r['timestamp_ns']):int(r['source_frame_index']) for r in csv.DictReader(f)}
        self.frame_map_path=Path(path)

    def request_color(self,meta):
        source_index=self.frame_map.get(meta['timestamp_ns'])
        if source_index is None:self.raw_hint.setText('灰度输入 · 彩色原片需要 source_frames.csv 同步映射')
        else:self.color.ask(source_index,(meta['timestamp_ns'],source_index))

    def show_ready_live(self):
        if self.pending_live is None:return
        snapshot=self.pending_live;meta=snapshot.meta;source=self.frame_map.get(meta['timestamp_ns']);image=None
        if self.color and source is not None:
            image=self.color.take((meta['timestamp_ns'],source))
            if image is None and not self.color.error and time.perf_counter()-self.pending_since<.15:
                self.request_color(meta);return
            if image is not None and self.live_cloud:
                crc=self.color.take_crc((meta['timestamp_ns'],source))
                if crc!=meta.get('raw_gray_crc'):raise ValueError('彩色原片与当前 FPGA 输入 CRC 不一致，停止显示')
        self.pending_live=None;self.show_snapshot(snapshot)
        if image is not None:
            self.raw.set_image(image);self.raw_hint.setText('彩色原片 · 按源帧号同步');self.latest_color_index=meta['frame_index']

    def toggle_pause(self):
        if self.dense_result and self.dense_frames:
            restart=not self.playing and self.index==len(self.dense_frames)-1
            if restart:self.seek_dense(0)
            self.playing=not self.playing
            self.dense_clock=time.perf_counter()
            cursor=self.dense_wanted if self.dense_seek_pending else max(0,self.index)
            self.dense_pts=self.dense_frames[0 if restart else cursor]['pts_s']
            self.play.setText('暂停回放' if self.playing else '继续回放')
            if not self.playing:self.metric_labels['fps'].setText('0.0')
            self.mode.setText('视频回放' if self.dense_video else '关键帧回放')
            return
        if self.record:
            if not self.playing and self.index==len(self.record.paths)-1:self.seek(0)
            self.playing=not self.playing;self.next_due=time.perf_counter();self.mode.setText('记录回放')
        else:self.paused=not self.paused
        self.play.setText('继续显示' if (self.paused or (self.record and not self.playing)) else '暂停显示')

    def tick(self):
        now=time.perf_counter()
        try:
            if self.live:
                if self.live_cloud and self.live.state in ('ERROR','CANCELLED'):
                    self.fail_live(self.live.error or '实际处理停止')
                if self.live_cloud and self.live.generation!=self.dense_generation:
                    self.dense_generation=self.live.generation;self.live_cloud.close()
                    self.live_cloud=LiveChunkLayer(self.map_view);self.scene.reset();self.pending_live=None
                    self.map_view.update_scene(self.scene)
                state=self.live.state
                label=dict(COMPLETED='处理已完成',RUNNING='实时建图' if self.live_cloud else '实时连接',CHECKING_FPGA='正在验证 FPGA 实际加速',INITIALIZING='加载词典 / 初始化',DRAINING='接收末批点块',CONNECTED='等待图像',CONNECTING='连接中',DISCONNECTED='连接已断开',ERROR='数据源失败',WAITING='等待数据源').get(state,state)
                if state=='RUNNING' and self.live.last_arrival and now-self.live.last_arrival>2:label='等待新帧'
                self.mode.setText('处理失败 · 已停止' if self.live_failure else ('显示已暂停' if self.paused else label))
                if not self.paused and not self.live_failure:
                    self.show_ready_live()
                    if self.pending_live is None:
                        snap=self.live.take()
                        if snap:
                            if self.live_cloud and getattr(self.live,'input_kind','video')!='camera_bridge' and snap.meta['timestamp_ns'] not in self.frame_map:raise ValueError('当前会话缺少准确源帧映射')
                            self.pending_live=snap;self.pending_since=now;self.show_ready_live()
                if self.live.error and not self.live_cloud:self.statusBar().showMessage(self.live.error+'；将自动重连')
                if self.live_cloud and not self.paused:
                    for meta,points in self.live.take_chunks():
                        before=self.live_cloud.counts()[0]
                        self.live_cloud.add(meta,points)
                        if before==0 and self.live_cloud.counts()[0]:self.map_view.fit(self.scene)
                    chunks,points,displayed=self.live_cloud.counts()
                    self.info.setText(f'实时点块 {chunks}\n实际彩色点 {points:,}\n显示 {displayed:,}\n{getattr(self,"depth_backend_label","NPU")} 关键帧增量\n位姿优化按块更新')
                    self.map_hint.setText(f'MAP {self.scene.map_id} · {chunks} 个增量点块 · {points:,} 点')
                    self.metric_labels['map'].setText(f'{points:,}')
                    self.map_view.auto_fit(self.scene)
            elif self.dense_result and self.dense_frames:
                self.tick_dense(now)
            elif self.record and self.playing and now>=self.next_due and not self.slider.isSliderDown():
                if self.index+1<len(self.record.paths):
                    self.index+=1;snap=self.record.read(self.index);self.show_snapshot(snap);self.slider.setValue(self.index)
                    next_index=min(self.index+1,len(self.record.paths)-1)
                    delay=(self.record.timeline[next_index]['timestamp_ns']-snap.meta['timestamp_ns'])/1e9
                    factor=(.5,1,2)[self.speed.currentIndex()];self.next_due=now+max(.015,min(.5,delay/factor))
                else:self.playing=False;self.mode.setText('回放结束')
            if self.color and self.current and not self.live_failure:
                index=self.current.meta['frame_index'];stamp=self.current.meta['timestamp_ns']
                image=self.color.take((stamp,self.frame_map.get(stamp)))
                if image is not None and self.latest_color_index!=index:
                    if self.live_cloud and self.color.take_crc((stamp,self.frame_map.get(stamp)))!=self.current.meta.get('raw_gray_crc'):
                        raise ValueError('彩色帧与当前 FPGA 输入 CRC 不一致')
                    self.raw.set_image(image);self.raw_hint.setText('彩色原片 · 按源帧号同步');self.latest_color_index=index
                if self.color.error:self.raw_hint.setText(self.color.error)
            if getattr(self.args,'metrics',None) and now-self.last_diagnostic>1:
                self.last_diagnostic=now
                state=dict(state=self.live.state if self.live else 'OFFLINE',error=self.live_failure,
                           frame=self.current.meta['frame_index'] if self.current else None,
                           pending=self.pending_live.meta['frame_index'] if self.pending_live else None,
                           received=self.live.received if self.live else 0,updated_ns=time.time_ns())
                state['displayed']=self.displayed;state['display_fps']=getattr(self,'current_display_rate',0.)
                if hasattr(self.map_view.view,'renderer_status'):
                    state['gpu']=self.map_view.view.renderer_status()
                    state['gpu_sparse']=self.sparse_view.view.renderer_status()
                path=Path(getattr(self.args,'desktop_status',None) or Path(self.args.metrics).with_name('desktop_status.json'));tmp=path.with_suffix('.tmp')
                tmp.write_text(json.dumps(state),encoding='utf-8');tmp.replace(path)
        except Exception as exc:
            if self.live_cloud:self.fail_live(str(exc))
            else:self.playing=False;self.statusBar().showMessage('显示错误：'+str(exc))

    def draw_feature_marks(self,image,features):
        for x,y,octave,mapped in features:
            cv2.circle(image,(round(x),round(y)),3,(135,230,60) if mapped else (40,188,245),1,cv2.LINE_AA)

    def show_snapshot(self,snapshot):
        if not self.scene.apply(snapshot):return
        draw_start=time.perf_counter()
        self.current=snapshot;self.latest_color_index=-1;meta=snapshot.meta;image=cv2.imdecode(np.frombuffer(snapshot.jpeg,np.uint8),cv2.IMREAD_COLOR)
        if image is None:raise ValueError('预览图像无法解码')
        self.raw.set_image(image);self.raw_hint.setText(('实时灰度预览 · 彩色深度另行低频采样' if self.live_cloud else '原始灰度输入') if meta['source_gray'] else '原始彩色输入')
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);overlay=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
        self.draw_feature_marks(overlay,meta['features'])
        self.feature_image.set_image(overlay)
        self.metric_labels['fps'].setText(f"{meta['processing_fps']:.1f}");self.metric_labels['features'].setText(str(meta['feature_count']))
        self.metric_labels['map'].setText(f'{len(self.scene.points):,}');self.map_hint.setText(f"MAP {meta['map_id']:02d}  ·  {len(self.scene.keyframes)} 关键帧")
        self.map_view.update_scene(self.scene);self.frame_text.setText(f"FRAME {meta['frame_index']:05d}")
        self.sparse_view.update_scene(self.scene)
        self.sparse_view.copy_sparse_points(self.map_view)
        if getattr(self.args,'separate_maps',False):self.sparse_view.view.setWindowTitle(f'原始稀疏地图 · {len(self.scene.points):,} 个三维点')
        self.sparse_hint.setText(f'当前帧 {meta["frame_index"]} · {len(self.scene.points):,} 个原始 SLAM 点')
        if self.live_cloud:
            if self.live_cloud.map_id!=self.scene.map_id:
                self.live_cloud.select_map(self.scene.map_id);self.live_cloud.update_fit_points()
            if meta['map_full']:self.live_cloud.update_poses(snapshot.keyframes)
        self.state_text.setText({0:'等待',1:'初始化中',2:'TRACKING',3:'短暂丢失',4:'LOST'}.get(meta['state'],str(meta['state'])))
        self.state_text.setStyleSheet('color:'+('#43dbc1' if meta['state']==2 else '#edb96c'))
        if self.scene.pose_valid:
            p=self.scene.pose[:3,3];self.pose_text.setText(f'相机位置  X {p[0]:+.3f}   Y {p[1]:+.3f}   Z {p[2]:+.3f}  · 相对单位')
        else:self.pose_text.setText('尚无有效位姿 · 不绘制虚假位置')
        self.displayed+=1;self.draw_times.append(time.perf_counter());recent=[t for t in self.draw_times if t>=self.draw_times[-1]-3]
        self.draw_frames.append(meta['frame_index'])
        rate=(len(recent)-1)/max(recent[-1]-recent[0],.001)
        self.current_display_rate=rate
        self.statusBar().showMessage(f"帧 {meta['frame_index']}  |  特征等待 {meta['feature_wait_ms']:.2f} ms  |  跟踪 {meta['track_ms']:.2f} ms  |  显示 {rate:.1f} FPS  |  单目相对尺度")
        if self.color:self.request_color(meta)
        self.draw_costs.append((time.perf_counter()-draw_start)*1000)

    def save_cloud(self):
        if self.live_cloud and self.checks['dense'].isChecked():
            path,_=QtWidgets.QFileDialog.getSaveFileName(self,'导出当前增量彩色地图','live_dense.ply','PLY (*.ply)')
            if path:
                from dense.ply import write_ply
                xyz,rgb=self.live_cloud.arrays();write_ply(Path(path),xyz,rgb)
                self.statusBar().showMessage(f'已导出当前地图 {len(xyz):,} 个彩色点；在线位姿尚可继续优化。')
            return
        if self.dense_result and self.checks['dense'].isChecked():
            path,_=QtWidgets.QFileDialog.getSaveFileName(self,'导出完整彩色点云','dense_map.ply','PLY (*.ply)')
            if path:
                import shutil
                if Path(path).resolve()!=self.dense_result.cloud.resolve():shutil.copyfile(self.dense_result.cloud,path)
                self.statusBar().showMessage(f'已导出完整 {len(self.dense_result.xyz):,} 个彩色点：'+path)
            return
        if not len(self.scene.points):self.message('当前还没有有效三维地图点');return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'导出SLAM原坐标点云','orb_map.ply','PLY (*.ply)')
        if path:export_ply(path,self.scene);self.statusBar().showMessage('已导出 '+path)

    def save_snapshot(self):
        directory=QtWidgets.QFileDialog.getExistingDirectory(self,'保存截图、位姿和当前原始快照')
        if directory:self.export_snapshot(Path(directory))

    def export_snapshot(self,directory):
        directory.mkdir(parents=True,exist_ok=True);self.grab().save(str(directory/'viewer.png'))
        if self.current:(directory/'frame.orbv').write_bytes(self.current.wire)
        if self.frame_map_path:
            import shutil
            if self.frame_map_path.resolve()!=(directory/'source_frames.csv').resolve():shutil.copy2(self.frame_map_path,directory/'source_frames.csv')
        export_ply(directory/'map.ply',self.scene)
        with (directory/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(['timestamp_ns']+[f'twc_{r}{c}' for r in range(4) for c in range(4)])
            for timestamp,pose in self.scene.trace:writer.writerow([timestamp,*pose.reshape(-1)])

    def message(self,error):QtWidgets.QMessageBox.warning(self,'ORB Studio',str(error))

    def clear_dense(self):
        if self.live_cloud:self.live_cloud.close();self.live_cloud=None
        self.slider.setEnabled(True);self.speed.setEnabled(True)
        if self.dense_result and self.color:self.color.close();self.color=None
        self.dense_result=None;self.map_view.dense_points=np.empty((0,3),np.float32)
        self.map_view.set_dense_source(None)
        self.metric_names['fps'].setText('SLAM 处理速度')
        self.dense_frames=[];self.dense_video=None;self.dense_seek_pending=False
        self.map_view.dense.setData(pos=np.empty((0,3)))

    def update_dense_size(self,*unused):
        if self.live_cloud:
            self.live_cloud.multiplier=self.splat_size.value()
            for c in self.live_cloud.chunks.values():
                size=live_point_diameter(c['meta']['voxel_edge'],len(c['points']),c['displayed'],self.splat_size.value())
                c['item'].setData(size=size if self.splat_auto.isChecked() else self.splat_size.value()*2,
                                  pxMode=not self.splat_auto.isChecked())
            return
        if not self.dense_result:return
        r=self.dense_result
        size=splat_diameter(r.report['voxel_edge'],self.map_view.dense_visible_count,len(self.map_view.dense_indices),self.splat_size.value())
        self.map_view.dense.setData(size=size if self.splat_auto.isChecked() else self.splat_size.value()*2,
                                    pxMode=not self.splat_auto.isChecked())
        self.info.setText(f"稠密点 {len(r.xyz):,}\n当前显示 {len(self.map_view.dense_indices):,}\n"
                          f"有效深度关键帧 {r.report['valid_depth_keyframes']}\n体素边长 {r.report['voxel_edge']:.4g}\n相对尺度 · 无表面补洞")

    def start_dense_replay(self,video=None):
        result=self.dense_result
        if not result or not result.replay:return
        if video:result.verify_video(video)
        if self.color:self.color.close();self.color=None
        self.dense_video=Path(video) if video else None
        if video:
            self.color=ColorVideo(video,RectifyReplay(result.replay),fast_seek=True);self.color.start()
            self.dense_frames=result.replay['frames']
        else:self.dense_frames=[f for f in result.replay['frames'] if 'rgb' in f]
        if not self.dense_frames:raise ValueError('没有可回放的真实图像')
        self.dense_factor=(.5,1,2)[self.speed.currentIndex()]
        self.dense_times=np.array([f['pts_s'] for f in self.dense_frames])
        self.dense_next_index=0;self.dense_skipped_display=0
        self.slider.setRange(0,len(self.dense_frames)-1)
        self.index=-1;self.paused=False;self.playing=True;self.seek_dense(0)
        self.mode.setText('视频回放' if video else '关键帧回放')
        self.metric_names['fps'].setText('回放显示速度')
        self.play.setText('暂停回放')
        self.statusBar().showMessage('按原始时间戳回放；显示最终点云与同次 SLAM 的相机位姿。特征仅在有真实观测的关键帧显示。')

    def seek_dense(self,index):
        index=max(0,min(int(index),len(self.dense_frames)-1))
        self.dense_wanted=index;self.dense_seek_pending=True
        self.dense_clock=time.perf_counter();self.dense_pts=self.dense_frames[index]['pts_s']
        if self.dense_video:self.color.ask(self.dense_frames[index]['source_frame_index'],('dense',index))

    def tick_dense(self,now):
        if self.slider.isSliderDown():return
        if self.dense_seek_pending:target=self.dense_wanted
        elif self.playing:target=self.dense_next_index
        else:return
        if target>=len(self.dense_frames):
            self.playing=False;self.play.setText('重新播放');self.mode.setText('回放结束');return
        frame=self.dense_frames[target]
        factor=(.5,1,2)[self.speed.currentIndex()]
        # A speed change starts a new clock segment without jumping over frames.
        if getattr(self,'dense_factor',factor)!=factor:
            self.dense_clock=now;self.dense_pts=self.dense_frames[max(0,self.index)]['pts_s']
        self.dense_factor=factor
        if not self.dense_seek_pending and now<self.dense_clock+(frame['pts_s']-self.dense_pts)/factor:return
        if self.dense_video:
            image=self.color.take(('dense',target))
            if image is None:
                if self.color.error:raise ValueError(self.color.error)
                self.color.ask(frame['source_frame_index'],('dense',target));return
        else:
            image=cv2.imread(str(self.dense_result._file(frame['rgb'])))
            if image is None:raise ValueError('回放关键帧图像缺失')
        if self.dense_seek_pending:
            self.dense_clock=now;self.dense_pts=frame['pts_s']
        self.dense_seek_pending=False;self.index=target;self.slider.setValue(target)
        self.raw.set_image(image);self.raw_hint.setText('原片回放 · 源帧 %d'%frame['source_frame_index'])
        overlay=cv2.cvtColor(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        for u,v in frame.get('uv',[]):cv2.circle(overlay,(round(u),round(v)),3,(135,230,60),1,cv2.LINE_AA)
        self.feature_image.set_image(overlay)
        if 'keyframe_id' in frame:
            self.feature_hint.setText('关键帧 %d · %d 个真实可靠观测'%(frame['keyframe_id'],len(frame['uv'])))
            self.metric_labels['features'].setText(str(len(frame['uv'])))
        else:
            self.feature_hint.setText('普通视频帧 · 本次记录未保存逐帧二维特征');self.metric_labels['features'].setText('—')
        self.scene.pose_valid=frame['twc'] is not None
        if self.scene.pose_valid:
            self.scene.pose=np.array(frame['twc'],np.float32)
            p=self.scene.pose[:3,3];self.pose_text.setText('同次最终轨迹  X %.3f  Y %.3f  Z %.3f'%tuple(p))
        else:self.pose_text.setText('该帧没有有效 SLAM 位姿')
        self.map_view.update_scene(self.scene)
        self.state_text.setText('REPLAY · FINAL MAP')
        elapsed=frame['pts_s']-self.dense_frames[0]['pts_s'];duration=self.dense_frames[-1]['pts_s']-self.dense_frames[0]['pts_s']
        self.frame_text.setText('%05d / %05d · %.1f / %.1f s'%(target+1,len(self.dense_frames),elapsed,duration))
        # Display follows source time even if a costly redraw misses a frame.
        # This never removes frames from SLAM/depth processing, which is already complete.
        due=self.dense_pts+max(0.,now-self.dense_clock)*factor
        latest=min(len(self.dense_frames)-1,int(np.searchsorted(self.dense_times,due,side='right'))-1) if self.playing else target
        self.dense_next_index=max(target+1,latest)
        self.dense_skipped_display+=max(0,self.dense_next_index-target-1)
        if self.dense_video and self.dense_next_index<len(self.dense_frames):
            self.color.ask(self.dense_frames[self.dense_next_index]['source_frame_index'],('dense',self.dense_next_index))
        self.draw_times.append(now);self.draw_frames.append(frame['source_frame_index']);self.displayed+=1
        recent=[t for t in self.draw_times if t>=now-2]
        rate=(len(recent)-1)/max(.001,recent[-1]-recent[0]) if len(recent)>1 and self.playing else 0.
        self.metric_labels['fps'].setText('%.1f'%rate)

    def choose_dense(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'打开建模 result.json','','建模结果 (result.json *.json)')
        if path:self.open_dense(path)

    def open_dense(self,path):
        try:
            candidate=Path(path)
            if candidate.is_dir():candidate=candidate/'result.json'
            report=json.loads(candidate.read_text(encoding='utf-8-sig'))
            map_id=None
            if 'maps' in report:
                maps=[m for m in report['maps'] if m.get('points',0)>0]
                if len(maps)>1:
                    label,accepted=QtWidgets.QInputDialog.getItem(self,'选择独立地图','地图不会合并坐标系',
                        [str(m['map_id']) for m in maps],0,False)
                    if not accepted:return
                    map_id=int(label)
            result=DenseResult(candidate,map_id)
            if self.live_cloud:self.live_cloud.close();self.live_cloud=None
            if self.live:self.live.close();self.live=None
            self.record=None;self.playing=False;self.scene.reset();self.current=None
            self.slider.setEnabled(True);self.speed.setEnabled(True)
            self.dense_frames=[];self.dense_video=None;self.dense_seek_pending=False
            self.dense_result=result;self.scene.map_id=result.report['map_id']
            self.scene.points=result.sparse_xyz;self.scene.keyframes=result.poses
            self.scene.pose_valid=False
            if len(result.poses)>1:
                pairs=np.stack((result.poses[:-1,:3,3],result.poses[1:,:3,3]),axis=1).reshape(-1,3)
                self.scene.segments.extend(pairs[-10000:])
            self.map_view.update_scene(self.scene)
            xyz,rgb=result.sampled();self.map_view.dense_points=xyz
            self.sparse_view.update_scene(self.scene);self.sparse_view.copy_sparse_points(self.map_view)
            self.map_view.set_dense_source(result)
            self.map_view.dense.setData(pos=view_points(xyz),color=np.c_[rgb.astype(np.float32)/255.,np.ones(len(rgb),np.float32)])
            self.update_dense_size()
            self.map_view.fit(self.scene);self.checks['dense'].setChecked(True)
            self.checks['keyframes'].setChecked(False);self.checks['points'].setChecked(False)
            self.mode.setText('离线彩色建模');self.map_hint.setText(f"MAP {result.report['map_id']} · 彩色稠密点云")
            self.metric_labels['map'].setText(f'{len(result.xyz):,}')
            self.info.setText(f"稠密点 {len(result.xyz):,}\n显示 {len(xyz):,}\n有效深度关键帧 {result.report['valid_depth_keyframes']}\n"
                              f"体素边长 {result.report['voxel_edge']:.4g}\n相对尺度 · 无表面补洞")
            self.state_text.setText('DENSE RESULT');self.pose_text.setText('最终关键帧位姿 · 原始相对坐标')
            self.statusBar().showMessage('已加载彩色稠密结果；图层可独立切换，导出保留全部点。')
            if result.report.get('preview_rgb'):
                image=cv2.imread(str(result._file(result.report['preview_rgb'])))
                if image is None:raise ValueError('建模关键帧原色图缺失')
                self.raw.set_image(image);self.raw_hint.setText('真实建模关键帧 · 校正后的彩色工作图')
                overlay=cv2.cvtColor(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
                points=json.loads(result._file(result.report['preview_features']).read_text())
                for u,v in points:cv2.circle(overlay,(round(u),round(v)),3,(135,230,60),1,cv2.LINE_AA)
                self.feature_image.set_image(overlay);self.feature_hint.setText('可靠 SLAM 观测 · 特征来自 FPGA')
                self.metric_labels['features'].setText(str(len(points)))
                self.frame_text.setText(f"源帧 {result.report['preview_source_frame']} · 关键帧 {result.report['preview_keyframe']}")
            if result.replay:self.start_dense_replay(self.args.video)
            else:
                self.play.setText('此结果尚无回放索引');self.slider.setRange(0,0)
        except Exception as exc:self.message(exc)
    def closeEvent(self,event):
        self.timer.stop()
        if hasattr(self,'demo_controls'):self.demo_controls.shutdown()
        if getattr(self.args,'metrics',None):
            gaps=np.diff(np.array(self.draw_times))*1000;costs=np.array(self.draw_costs)
            def stats(values):return dict(mean=float(np.mean(values)),p99=float(np.percentile(values,99)),max=float(np.max(values))) if len(values) else {}
            result=dict(displayed=self.displayed,display_fps=(len(self.draw_times)-1)/max(self.draw_times[-1]-self.draw_times[0],.001) if len(self.draw_times)>1 else 0,
                        frame_gap_ms=stats(gaps),render_cpu_ms=stats(costs),source='live' if self.live else ('dense_replay' if self.dense_result else 'recording'),
                        received=self.live.received if self.live else 0,replaced=self.live.replaced if self.live else 0)
            result.update(previous_connections=self.connection_history,first_frame=self.draw_frames[0] if self.draw_frames else None,
                          last_frame=self.draw_frames[-1] if self.draw_frames else None,playout_buffer_ms=getattr(self.args,'buffer_ms',0))
            if hasattr(self.map_view.view,'renderer_status'):
                result['gpu']=self.map_view.view.renderer_status()
                result['gpu_sparse']=self.sparse_view.view.renderer_status()
            if self.live_cloud:
                result.update(dense_chunks=self.live_cloud.counts()[0],dense_points=self.live_cloud.counts()[1],
                              dense_buffer_uploads=self.live_cloud.uploads,dense_pose_updates=self.live_cloud.pose_updates)
            self.args.metrics.parent.mkdir(parents=True,exist_ok=True);self.args.metrics.write_text(json.dumps(result,indent=2)+'\n')
        if self.live:self.live.close()
        if self.live_cloud:self.live_cloud.close()
        if getattr(self.args,'separate_maps',False):
            for view in (self.map_view.view,self.sparse_view.view):
                if hasattr(view,'surface'):view.surface.close()
                else:view.close()
        if self.color:self.color.close()
        event.accept()


def main():
    p=argparse.ArgumentParser();p.add_argument('--connect',default=os.getenv('ORB60_VIEWER_HOST',''))
    p.add_argument('--recording',type=Path);p.add_argument('--video',type=Path)
    p.add_argument('--dense',type=Path,help='Offline colored reconstruction result.json or directory')
    p.add_argument('--dense-live',help='Actual processing stream with per-keyframe dense deltas, host:port')
    p.add_argument('--frame-map',type=Path,help='Dataset source_frames.csv mapping timestamps to original MP4 frame indices')
    p.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'build/local/viewer.json')
    p.add_argument('--screenshot',type=Path,help='Application QA: save its own window after rendering')
    p.add_argument('--screenshot-frame',type=int,default=-1);p.add_argument('--exit-after',type=float,default=0)
    p.add_argument('--metrics',type=Path,help='Save display update timing at close')
    p.add_argument('--desktop-status',type=Path,help='Optional isolated live diagnostic file for this GUI instance')
    p.add_argument('--control-file',type=Path,help='Owned launcher control mailbox: stop or restart actual processing')
    p.add_argument('--demo-controller',help='Two-stage RK controller URL, e.g. http://rk3588:5610')
    p.add_argument('--separate-maps',action='store_true',help='Keep video/controls in main window and show two independent 3D windows')
    p.add_argument('--processor',default='RK3588',help='Compute endpoint label, e.g. PC / WSL')
    p.add_argument('--buffer-ms',type=int,default=0,choices=range(0,251),metavar='0..250',help='Bounded timestamp playout for a paced live source')
    args=p.parse_args()
    if not args.demo_controller and not args.recording and not args.connect and not args.dense and not args.dense_live and args.config.is_file():
        config=json.loads(args.config.read_text(encoding='utf-8-sig'))
        base=args.config.parent
        for name in ('recording','video','frame_map'):
            if getattr(args,name) is None and config.get(name):
                path=Path(config[name]);setattr(args,name,path if path.is_absolute() else (base/path).resolve())
        if config.get('connect'):args.connect=config['connect']
    if os.getenv('QT_OPENGL')=='software':QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    if getattr(args,'separate_maps',False) and os.getenv('ORB60_VIEWER_RENDERER') not in ('gles','egl-raster'):
        # pyqtgraph caches point shader programs globally. Independent windows
        # must share GL resources; otherwise only the first window draws points.
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if hasattr(gl,'configure'):gl.configure()
    app=QtWidgets.QApplication(sys.argv[:1]);app.setApplicationName('ORB Studio')
    window=Window(args);window.show()
    def present_main_window():
        # Address the actual QWidget handle, never a Qt OpenGL helper surface.
        window.showNormal();window.raise_();window.activateWindow()
        if sys.platform=='win32':
            import ctypes
            user32=ctypes.windll.user32
            user32.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
            user32.SetForegroundWindow.argtypes=[ctypes.c_void_p]
            handle=int(window.winId());user32.ShowWindow(handle,9);user32.SetForegroundWindow(handle)
    QtCore.QTimer.singleShot(250,present_main_window)
    if args.screenshot:
        def capture():
            if window.record:
                window.playing=False;window.seek(args.screenshot_frame if args.screenshot_frame>=0 else len(window.record.paths)-1)
            elif window.live and (window.current is None or window.current.meta['frame_index']<max(args.screenshot_frame,110)):
                QtCore.QTimer.singleShot(200,capture);return
            deadline=time.perf_counter()+20
            def save_when_ready():
                waiting=window.color and window.current and window.frame_map and window.latest_color_index!=window.current.meta['frame_index']
                if waiting and time.perf_counter()<deadline:
                    QtCore.QTimer.singleShot(200,save_when_ready);return
                window.export_snapshot(args.screenshot)
            QtCore.QTimer.singleShot(1800,save_when_ready)
        QtCore.QTimer.singleShot(1200,capture)
    if args.exit_after:QtCore.QTimer.singleShot(int(args.exit_after*1000),window.close)
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
