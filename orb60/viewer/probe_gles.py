"""Small real-display GPU capability probe, independent of mapping services."""
import json
from pathlib import Path
import sys
from PySide6 import QtCore,QtGui,QtWidgets,QtOpenGLWidgets
from OpenGL import GLES3

fmt=QtGui.QSurfaceFormat();fmt.setRenderableType(QtGui.QSurfaceFormat.RenderableType.OpenGLES)
fmt.setVersion(3,0);fmt.setDepthBufferSize(24);QtGui.QSurfaceFormat.setDefaultFormat(fmt)
app=QtWidgets.QApplication([])

class Probe(QtOpenGLWidgets.QOpenGLWidget):
    def initializeGL(self):
        def name(key):
            value=GLES3.glGetString(key)
            if isinstance(value,bytes):return value.decode()
            import ctypes
            return ctypes.cast(value,ctypes.c_char_p).value.decode()
        result=dict(vendor=name(GLES3.GL_VENDOR),renderer=name(GLES3.GL_RENDERER),version=name(GLES3.GL_VERSION))
        Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    def paintGL(self):
        GLES3.glClearColor(.04,.12,.16,1);GLES3.glClear(GLES3.GL_COLOR_BUFFER_BIT)

window=Probe();window.setWindowTitle('ORB GPU probe');window.resize(200,120);window.show()
QtCore.QTimer.singleShot(2500,app.quit)
app.exec()
