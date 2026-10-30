"""Mali GLES renders retained VBOs into an owned FBO; Qt only presents pixels.

No EGL native window, QOpenGLWidget or Qt GL context participates in rendering.
The readback cost is included in reported frame times.
"""
import ctypes
import time
from collections import deque
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets
from OpenGL import EGL as E
from OpenGL import GLES3 as G
import gles_view as base
from gles_view import GLScatterPlotItem,GLLinePlotItem,GLGridItem,GLAxisItem


def configure():pass


class Buffer:
    def create(self):self.id=int(G.glGenBuffers(1));return bool(self.id)
    def bind(self):G.glBindBuffer(G.GL_ARRAY_BUFFER,self.id)
    def allocate(self,data,size):G.glBufferData(G.GL_ARRAY_BUFFER,size,data,G.GL_STATIC_DRAW)
    def destroy(self):G.glDeleteBuffers(1,[self.id])


class Vao:
    def __init__(self):self.id=int(G.glGenVertexArrays(1))
    def bind(self):G.glBindVertexArray(self.id)
    def release(self):G.glBindVertexArray(0)


class Program:
    def __init__(self):
        shaders=[]
        try:
            for kind,source in [(G.GL_VERTEX_SHADER,base.VERTEX),(G.GL_FRAGMENT_SHADER,base.FRAGMENT)]:
                shader=G.glCreateShader(kind);shaders.append(shader)
                G.glShaderSource(shader,source);G.glCompileShader(shader)
                ok=ctypes.c_int();G.glGetShaderiv(shader,G.GL_COMPILE_STATUS,ctypes.byref(ok))
                if not ok.value:raise RuntimeError('Mali shader compile failed')
            self.id=G.glCreateProgram()
            for shader in shaders:G.glAttachShader(self.id,shader)
            G.glLinkProgram(self.id)
            ok=ctypes.c_int();G.glGetProgramiv(self.id,G.GL_LINK_STATUS,ctypes.byref(ok))
            if not ok.value:raise RuntimeError('Mali shader link failed')
        finally:
            for shader in shaders:G.glDeleteShader(shader)
    def bind(self):G.glUseProgram(self.id);return True
    def release(self):G.glUseProgram(0)
    def enableAttributeArray(self,i):G.glEnableVertexAttribArray(i)
    def disableAttributeArray(self,i):G.glDisableVertexAttribArray(i)
    def setAttributeBuffer(self,i,kind,offset,count,stride):
        G.glVertexAttribPointer(i,count,kind,False,stride,ctypes.c_void_p(offset))


class Context:
    def __init__(self):
        self.display=E.eglGetDisplay(E.EGL_DEFAULT_DISPLAY)
        major,minor=E.EGLint(),E.EGLint()
        if not E.eglInitialize(self.display,major,minor):raise RuntimeError('EGL initialize failed')
        E.eglBindAPI(E.EGL_OPENGL_ES_API)
        attrs=(E.EGLint*13)(E.EGL_SURFACE_TYPE,E.EGL_PBUFFER_BIT,E.EGL_RENDERABLE_TYPE,0x40,
                            E.EGL_RED_SIZE,8,E.EGL_GREEN_SIZE,8,E.EGL_BLUE_SIZE,8,E.EGL_ALPHA_SIZE,8,E.EGL_NONE)
        configs=(E.EGLConfig*1)();count=E.EGLint()
        if not E.eglChooseConfig(self.display,attrs,configs,1,count) or not count.value:
            raise RuntimeError('No EGL GLES3 pbuffer config')
        self.surface=E.eglCreatePbufferSurface(self.display,configs[0],(E.EGLint*5)(E.EGL_WIDTH,1,E.EGL_HEIGHT,1,E.EGL_NONE))
        self.ctx=E.eglCreateContext(self.display,configs[0],E.EGL_NO_CONTEXT,(E.EGLint*3)(E.EGL_CONTEXT_CLIENT_VERSION,3,E.EGL_NONE))
        self.make_current()
    def make_current(self):
        if not E.eglMakeCurrent(self.display,self.surface,self.surface,self.ctx):raise RuntimeError('EGL make-current failed')


class GLViewWidget(base.GLViewWidget):
    def __init__(self):
        QtWidgets.QWidget.__init__(self)
        self.items=[];self.background=QtGui.QColor('#0a1421')
        self.opts=dict(distance=8.,elevation=25.,azimuth=-60.,center=QtGui.QVector3D(),fov=60.)
        self.mouse=None;self.program=None;self.uploads=0;self.upload_bytes=0;self.renderer={}
        self.paint_ms=deque(maxlen=600);self.paint_times=deque(maxlen=600)
        self.egl=None;self.fbo=None;self.fbo_size=None;self.image=QtGui.QImage()
        self.surface=self;self.detached=False;self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    def width(self):return QtWidgets.QWidget.width(self)
    def height(self):return QtWidgets.QWidget.height(self)
    def devicePixelRatioF(self):return 1.0  # Owned FBO uses logical QWidget pixels.
    def update(self,*unused):QtWidgets.QWidget.update(self)
    def setWindowTitle(self,title):QtWidgets.QWidget.setWindowTitle(self,title)
    def hideEvent(self,event):QtWidgets.QWidget.hideEvent(self,event)
    def showEvent(self,event):QtWidgets.QWidget.showEvent(self,event)
    def resizeEvent(self,event):QtWidgets.QWidget.resizeEvent(self,event)
    def detach(self,title,rectangle):
        self.detached=True;self.setParent(None);self.setWindowFlags(QtCore.Qt.WindowType.Window)
        self.setWindowTitle(title);self.setGeometry(rectangle);self.show()
    def create_buffer(self):return Buffer()
    def makeCurrent(self):self.egl.make_current()
    def doneCurrent(self):pass
    def removeItem(self,item):
        if item in self.items:
            if item.buffer is not None:self.makeCurrent();item.buffer.destroy();item.buffer=None
            self.items.remove(item);item.owner=None;self.update()
    def defaultFramebufferObject(self):return self.fbo
    def initializeGL(self):
        self.egl=Context()
        def string(key):return ctypes.cast(G.glGetString(key),ctypes.c_char_p).value.decode()
        self.renderer=dict(vendor=string(G.GL_VENDOR),renderer=string(G.GL_RENDERER),version=string(G.GL_VERSION),presentation='EGL FBO + raster Qt presentation')
        if 'mali' not in self.renderer['renderer'].lower():raise RuntimeError('Mali hardware required: '+str(self.renderer))
        self.program=Program();self.vao=Vao()
        self.uniforms={name:int(G.glGetUniformLocation(self.program.id,name.encode())) for name in
                       ('view','projection','viewport_height','model','size','pixel_size','points')}
        self.fbo=int(G.glGenFramebuffers(1));self.texture=int(G.glGenTextures(1));self.depth=int(G.glGenRenderbuffers(1))
        print('ORB_GPU '+str(self.renderer),flush=True)
    def resize_fbo(self,w,h):
        if self.fbo_size==(w,h):return
        G.glBindFramebuffer(G.GL_FRAMEBUFFER,self.fbo)
        G.glBindTexture(G.GL_TEXTURE_2D,self.texture)
        G.glTexImage2D(G.GL_TEXTURE_2D,0,G.GL_RGBA8,w,h,0,G.GL_RGBA,G.GL_UNSIGNED_BYTE,None)
        G.glTexParameteri(G.GL_TEXTURE_2D,G.GL_TEXTURE_MIN_FILTER,G.GL_NEAREST)
        G.glTexParameteri(G.GL_TEXTURE_2D,G.GL_TEXTURE_MAG_FILTER,G.GL_NEAREST)
        G.glFramebufferTexture2D(G.GL_FRAMEBUFFER,G.GL_COLOR_ATTACHMENT0,G.GL_TEXTURE_2D,self.texture,0)
        G.glBindRenderbuffer(G.GL_RENDERBUFFER,self.depth)
        G.glRenderbufferStorage(G.GL_RENDERBUFFER,G.GL_DEPTH_COMPONENT24,w,h)
        G.glFramebufferRenderbuffer(G.GL_FRAMEBUFFER,G.GL_DEPTH_ATTACHMENT,G.GL_RENDERBUFFER,self.depth)
        if G.glCheckFramebufferStatus(G.GL_FRAMEBUFFER)!=G.GL_FRAMEBUFFER_COMPLETE:raise RuntimeError('Incomplete owned GPU FBO')
        self.fbo_size=(w,h);self.readback=np.empty((h,w,4),np.uint8)
    def paintEvent(self,event):
        if getattr(self,'render_failure',None):
            painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor('#300f0f'))
            painter.setPen(QtGui.QColor('white'));painter.drawText(self.rect(),QtCore.Qt.AlignmentFlag.AlignCenter,'GPU render failed: '+self.render_failure);painter.end();return
        began=time.perf_counter()
        try:
            if self.egl is None:self.initializeGL()
            self.makeCurrent();w=max(1,self.width());h=max(1,self.height());self.resize_fbo(w,h)
            base.GLViewWidget.paintGL(self)
            G.glReadPixels(0,0,w,h,G.GL_RGBA,G.GL_UNSIGNED_BYTE,self.readback)
            rgb=np.ascontiguousarray(self.readback[::-1]);self.image=QtGui.QImage(rgb.data,w,h,w*4,QtGui.QImage.Format.Format_RGBA8888).copy()
            painter=QtGui.QPainter(self);painter.drawImage(self.rect(),self.image);painter.end()
            self.paint_ms[-1]=(time.perf_counter()-began)*1000
        except Exception as exc:
            import traceback
            if not getattr(self,'error_reported',False):traceback.print_exc();self.error_reported=True
            self.render_failure=str(exc)
            print('ORB_GPU_FAILED '+repr(exc),flush=True)
            painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor('#300f0f'))
            painter.setPen(QtGui.QColor('white'));painter.drawText(self.rect(),QtCore.Qt.AlignmentFlag.AlignCenter,'GPU render failed: '+str(exc));painter.end()
    def grabFramebuffer(self):return self.image.copy()
    def renderer_status(self):
        return dict(super().renderer_status(),error=getattr(self,'render_failure',None))
