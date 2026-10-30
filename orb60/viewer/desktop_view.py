"""Compatible desktop GL windows; no native EGL child composition."""
import time
from collections import deque
import numpy as np
from PySide6 import QtCore,QtGui
import pyqtgraph.opengl as original
from pyqtgraph.opengl import GLScatterPlotItem,GLLinePlotItem,GLGridItem,GLAxisItem


def configure():
    fmt=QtGui.QSurfaceFormat();fmt.setRenderableType(QtGui.QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(2,1);fmt.setDepthBufferSize(24);fmt.setSwapInterval(0)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)


class GLViewWidget(original.GLViewWidget):
    def __init__(self):
        super().__init__();self.times=deque(maxlen=600);self.costs=deque(maxlen=600);self.driver={}
    def detach(self,title,rectangle):
        self.setParent(None);self.setWindowFlags(QtCore.Qt.WindowType.Window)
        self.setWindowTitle(title);self.setGeometry(rectangle);self.show()
    def initializeGL(self):
        super().initializeGL()
        from OpenGL import GL
        self.driver={key:GL.glGetString(value).decode() for key,value in
                     [('vendor',GL.GL_VENDOR),('renderer',GL.GL_RENDERER),('version',GL.GL_VERSION)]}
        print('ORB_DESKTOP_RENDERER '+str(self.driver),flush=True)
    def paintGL(self,*args,**kwargs):
        began=time.perf_counter();result=super().paintGL(*args,**kwargs)
        self.times.append(time.perf_counter());self.costs.append((time.perf_counter()-began)*1000);return result
    def renderer_status(self):
        times=list(self.times)
        return dict(self.driver,fps=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0,
                    paint_cpu_ms_p95=float(np.percentile(self.costs,95)) if self.costs else 0,
                    scatter_points=[len(i.pos) for i in self.items if isinstance(i,GLScatterPlotItem) and i.pos is not None and i.visible()],
                    mode='compatible separate desktop GL; display sampling only')
