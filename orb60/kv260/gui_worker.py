"""Run the existing UI with the KV260 GLES2 renderer without changing RK code."""
import os
from pathlib import Path
import sys
import json
import time

viewer=Path(__file__).resolve().parents[1]/'viewer'
sys.path.insert(0,str(viewer))
from orb60.kv260 import gles2_view
sys.modules['gles_view']=gles2_view
os.environ['ORB60_VIEWER_RENDERER']='gles'
sys.argv[0]=str(viewer/'app.py')
import app as ui
from PySide6 import QtCore,QtGui,QtWidgets


class KVImageView(ui.ImageView):
    def __init__(self):
        super().__init__();self.kv_image_revision=0;self.kv_scaled_key=None;self.kv_scaled=None

    def set_image(self,image):
        if os.getenv('ORB60_GUI_FAST_PREVIEW')!='1':return super().set_image(image)
        if image.dtype!=ui.np.uint8 or image.ndim not in (2,3) or (image.ndim==3 and image.shape[2]!=3):raise ValueError('BGR8/gray8 preview required')
        image=ui.np.ascontiguousarray(image);h,w=image.shape[:2]
        fmt=QtGui.QImage.Format.Format_Grayscale8 if image.ndim==2 else QtGui.QImage.Format.Format_BGR888
        self.image=QtGui.QImage(image.data,w,h,image.strides[0],fmt).copy();self.kv_image_revision+=1;self.update()

    def paintEvent(self,event):
        if os.getenv('ORB60_GUI_FAST_PREVIEW')!='1' or self.image is None:return super().paintEvent(event)
        target=self.image_rect();key=(self.kv_image_revision,target.width(),target.height())
        if key!=self.kv_scaled_key:
            self.kv_scaled=self.image.scaled(target.size(),QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,QtCore.Qt.TransformationMode.FastTransformation);self.kv_scaled_key=key
        painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor('#070d16'));painter.drawImage(target.topLeft(),self.kv_scaled)


ui.ImageView=KVImageView


class KVColorVideo(ui.ColorVideo):
    def run_exact(self):
        if os.getenv('ORB60_GUI_SOURCE_SCOPE')=='two_board_live':
            from orb60.kv260.video_preview import run_bgr_preview
            return run_bgr_preview(self)
        return super().run_exact()


ui.ColorVideo=KVColorVideo


class KVWindow(ui.Window):
    def show(self):
        if getattr(self,'kv_gpu_only',False):
            self.hide()
            for panel in (self.map_view,self.sparse_view):panel.view.surface.show()
            return
        return super().show()

    def showNormal(self):
        if getattr(self,'kv_gpu_only',False):return self.show()
        return super().showNormal()

    def show_snapshot(self,snapshot):
        if not getattr(self,'kv_gpu_only',False):return super().show_snapshot(snapshot)
        if not self.scene.apply(snapshot):return
        began=time.perf_counter();self.current=snapshot;meta=snapshot.meta
        self.map_view.update_scene(self.scene);self.sparse_view.update_scene(self.scene);self.sparse_view.copy_sparse_points(self.map_view)
        if self.live_cloud:
            if self.live_cloud.map_id!=self.scene.map_id:self.live_cloud.select_map(self.scene.map_id);self.live_cloud.update_fit_points()
            if meta['map_full']:self.live_cloud.update_poses(snapshot.keyframes)
        self.displayed+=1;now=time.perf_counter();self.draw_times.append(now);self.draw_frames.append(meta['frame_index'])
        recent=[t for t in self.draw_times if t>=now-3];self.current_display_rate=(len(recent)-1)/max(recent[-1]-recent[0],.001)
        if now-getattr(self,'kv_last_titles',0)>.5:
            self.kv_last_titles=now;prefix='历史处理' if self.record else '近期处理';rate=f"{prefix} {meta['processing_fps']:.1f} FPS · 显示 {self.current_display_rate:.1f} FPS"
            self.map_view.view.setWindowTitle('彩色稠密点云 · DPU · '+rate)
            self.sparse_view.view.setWindowTitle(f'稀疏地图与轨迹 · {len(self.scene.points):,} 点 · '+rate)
            if os.getenv('ORB60_GUI_INPUT_KIND')=='live_camera':
                from .camera_status import label
                dense_points=self.live_cloud.counts()[1] if self.live_cloud else 0
                status=label(meta,len(self.scene.points),dense_points)
                self.map_view.view.setWindowTitle(status+' · '+rate)
                self.sparse_view.view.setWindowTitle(f'稀疏地图与轨迹 · {len(self.scene.points):,} 点 · '+status)
        self.draw_costs.append((time.perf_counter()-began)*1000)

    def draw_feature_marks(self,image,features):
        if os.getenv('ORB60_GUI_FAST_PREVIEW')=='1':
            from .feature_overlay import draw_fast
            return draw_fast(image,features)
        if os.getenv('ORB60_GUI_BATCH_FEATURES')=='1':
            from .feature_overlay import draw_batch
            return draw_batch(image,features)
        return super().draw_feature_marks(image,features)

    def connect_dense_live(self):
        super().connect_dense_live()
        if not self.live or not self.args.frame_map:return
        source=self.live;take=source.take
        from .source_frame_map import SourceFrameMapReader
        self.kv_frame_reader=SourceFrameMapReader(self.args.frame_map)
        expected=os.getenv('ORB60_GUI_INPUT_IDENTITIES')
        if expected:
            from .source_frame_map import FrozenFrameIdentities
            self.kv_expected_input=FrozenFrameIdentities(expected,os.getenv('ORB60_GUI_COLOR_IDENTITIES'))
        def take_with_local_identity():
            snapshot=take()
            if snapshot is not None and source.input_kind=='kv260_local_rgb':
                # The local producer flushes this exact identity before sending
                # the frame. Do not infer a video index from a rounded clock.
                self.frame_map=self.kv_frame_reader.update()
                self.frame_map_path=self.kv_frame_reader.path
                if snapshot.meta['timestamp_ns'] not in self.frame_map:raise ValueError('Exact local frame mapping is absent')
                if hasattr(self,'kv_expected_input'):self.kv_expected_input.check(snapshot.meta)
            return snapshot
        source.take=take_with_local_identity

    def tick(self):
        super().tick()
        if os.getenv('ORB60_GUI_SOURCE_SCOPE')=='two_board_live' and self.live:
            if time.monotonic()-getattr(self,'kv_last_status',0)>1:
                self.kv_last_status=time.monotonic()
                path=Path(os.environ['ORB60_GUI_LIVE_STATUS'])
                state={'state':self.live.state,'error':self.live_failure or self.live.error,
                       'frame':self.current.meta['frame_index'] if self.current else None,
                       'dense_counts':self.live_cloud.counts() if self.live_cloud else [0,0,0],
                       'dense_revisions':{'%d:%d'%key:chunk['meta']['revision'] for key,chunk in self.live_cloud.chunks.items()} if self.live_cloud else {},
                       'source_map_rows_parsed':self.kv_frame_reader.rows_parsed,
                       'map_id':self.scene.map_id,'updated_monotonic_ns':time.monotonic_ns()}
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(state)+'\n');tmp.replace(path)
        stop=os.getenv('ORB60_GUI_STOP_FILE')
        if stop and Path(stop).is_file():
            if self.args.screenshot:self.export_snapshot(self.args.screenshot)
            self.close();return

    def __init__(self,args):
        self.kv_gpu_only=os.getenv('ORB60_GUI_GPU_ONLY')=='1'
        self.depth_backend_label='PS MiDaS' if os.getenv('ORB60_GUI_DEPTH_BACKEND')=='ps_cpu' else 'DPU'
        super().__init__(args)
        if self.kv_gpu_only:
            if not getattr(args,'separate_maps',False):raise ValueError('GPU-only mode requires independent map windows')
            if self.color:self.color.close();self.color=None
            g=QtWidgets.QApplication.primaryScreen().availableGeometry();w=max(320,(g.width()-36)//2);h=max(240,g.height()-60)
            self.map_view.view.surface.setGeometry(QtCore.QRect(g.x()+12,g.y()+30,w,h))
            self.sparse_view.view.surface.setGeometry(QtCore.QRect(g.x()+24+w,g.y()+30,w,h))
        for label in self.findChildren(QtWidgets.QLabel):
            if 'ZYNQ FPGA' in label.text():label.setText(label.text().replace('ZYNQ FPGA','KV260 PL'))
            if 'DESKTOP' in label.text():label.setText(label.text().replace('DESKTOP','KV260 DISPLAY'))
            if label.text()=='LANDMARKS':label.setText('POINTS')
        if args.recording:
            self.metric_names['fps'].setText('历史记录处理速度')
            self.statusBar().showMessage('KV260 本机界面验证 · 正在回放历史记录，不代表当前 PL 或建图帧率')
        if args.dense:
            self.metric_names['fps'].setText('离线结果 / 非实时');self.metric_labels['fps'].setText('—')
        if os.getenv('ORB60_GUI_SOURCE_SCOPE')=='saved_poses_dpu':
            for label in self.findChildren(QtWidgets.QLabel):
                if 'KV260 PL' in label.text():label.setText(label.text().replace('KV260 PL','7015 保存特征'))
            self.statusBar().showMessage('KV260 实际 DPU 彩色点云 · 使用保存的 PS 位姿 · 当前为结果查看')
        if os.getenv('ORB60_GUI_SOURCE_SCOPE')=='two_board_live':
            for label in self.findChildren(QtWidgets.QLabel):
                if 'KV260 PL' in label.text():label.setText(label.text().replace('KV260 PL','7015 PL'))
            self.metric_names['fps'].setText('近期处理速度')
            self.metric_names['fps'].setToolTip('近期处理帧率，不代表整段视频或最终点云完成后的平均速度。')
            self.metric_names['map'].setText('已接收点数')
            self.metric_names['map'].setToolTip('按接收到的局部点块计数；融合导出的点数另行统计。')
            self.statusBar().showMessage('7015 实际 PL ORB · KV260 PS 建图 · DPU 关键帧深度 · Mali 显示')
            if os.getenv('ORB60_GUI_TASK_MODE')=='fixed_map_localization':
                self.depth_backend_label='保存的 DPU 点云'
                self.metric_names['fps'].setText('近期定位速度')
                self.statusBar().showMessage('7015 实际 PL ORB · KV260 PS 固定地图定位 · 显示同地图已保存的 DPU 彩色点云')
        if os.getenv('ORB60_GUI_SOURCE_SCOPE')=='saved_pl_replay':
            for label in self.findChildren(QtWidgets.QLabel):
                if 'KV260 PL' in label.text():label.setText(label.text().replace('KV260 PL','保存的 PL 特征'))
                elif label.text()=='ORB 特征 / 150 MHz':label.setText('历史真实特征输入')
            self.metric_names['fps'].setText('PS 保存特征回放')
            provenance=QtWidgets.QLabel('保存特征回放 · 当前 KV260 PL 未运行')
            provenance.setStyleSheet('color:#e4bf78')
            self.statusBar().addPermanentWidget(provenance)

    def export_snapshot(self,directory):
        super().export_snapshot(directory)
        # Native GLES windows are separate surfaces. Include their actual
        # framebuffer pixels in the owned screenshot, with no synthesized map.
        frames={name:panel.view.grabFramebuffer() for name,panel in [('map',self.map_view),('sparse',self.sparse_view)]}
        if self.kv_gpu_only:
            frames_list=list(frames.values());pixmap=QtGui.QPixmap(sum(f.width() for f in frames_list),max(f.height() for f in frames_list));pixmap.fill(QtCore.Qt.GlobalColor.black)
        else:pixmap=self.grab()
        painter=QtGui.QPainter(pixmap);x=0
        try:
            for name,panel in [('map',self.map_view),('sparse',self.sparse_view)]:
                view=panel.view;frame=frames[name]
                if frame.isNull():raise RuntimeError('Empty GLES2 framebuffer: '+name)
                frame.save(str(directory/(name+'_framebuffer.png')))
                if self.kv_gpu_only:painter.drawImage(x,0,frame);x+=frame.width()
                if not getattr(self.args,'separate_maps',False):
                    rect=QtCore.QRect(view.mapTo(self,QtCore.QPoint(0,0)),view.size())
                    painter.drawImage(rect,frame)
        finally:painter.end()
        if not pixmap.save(str(directory/'viewer.png')):raise RuntimeError('Cannot save complete KV260 UI snapshot')

    def closeEvent(self,event):
        super().closeEvent(event)
        if getattr(self.args,'metrics',None) and Path(self.args.metrics).is_file():
            p=Path(self.args.metrics);data=json.loads(p.read_text());data['gpu_only']=self.kv_gpu_only;data['video_decode_and_feature_overlay_skipped']=self.kv_gpu_only;p.write_text(json.dumps(data,indent=2)+'\n')


ui.Window=KVWindow
raise SystemExit(ui.main())
