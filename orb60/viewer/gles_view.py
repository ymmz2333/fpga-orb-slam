"""Retained-buffer GLES3 point/line renderer for RK Mali, without legacy desktop GL."""
import ctypes
import math
import time
from collections import deque
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets,QtOpenGL,QtOpenGLWidgets
from OpenGL import GLES3 as G


def configure():
    f=QtGui.QSurfaceFormat();f.setRenderableType(QtGui.QSurfaceFormat.RenderableType.OpenGLES)
    f.setVersion(3,0);f.setDepthBufferSize(24);f.setSwapInterval(1)
    QtGui.QSurfaceFormat.setDefaultFormat(f)


VERTEX='''#version 300 es
precision highp float;
layout(location=0) in vec3 position;
layout(location=1) in vec4 color;
uniform mat4 model,view,projection;
uniform float size,viewport_height;
uniform bool pixel_size;
out vec4 rgba;
void main(){
 vec4 p=view*model*vec4(position,1.0);
 gl_Position=projection*p;
 float d=pixel_size?size:size*viewport_height*projection[1][1]/max(0.00001,-p.z);
 gl_PointSize=clamp(d,1.0,3.0);
 rgba=color;
}'''
FRAGMENT='''#version 300 es
precision mediump float;
in vec4 rgba;
uniform bool points;
out vec4 result;
void main(){
 if(points){vec2 d=gl_PointCoord-vec2(0.5);if(dot(d,d)>0.25)discard;}
 result=rgba;
}'''


class Item:
    primitive=G.GL_POINTS
    def __init__(self,pos=None,color=(1,1,1,1),size=1,pxMode=True,**unused):
        self.pos=np.empty((0,3),np.float32);self.color=color;self.size=size;self.pxMode=pxMode
        self.visible=True;self.depth=0;self.depth_test=True;self.matrix=QtGui.QMatrix4x4()
        self.owner=None;self.buffer=None;self.dirty=True;self.count=0
        self.setData(pos=pos if pos is not None else self.pos,color=color)
    def changed(self):
        if self.owner:self.owner.update()
    def setData(self,**values):
        if 'pos' in values:self.pos=np.asarray(values['pos'],np.float32).reshape(-1,3);self.dirty=True
        if 'color' in values:self.color=values['color'];self.dirty=True
        if 'size' in values:self.size=float(values['size'])
        if 'pxMode' in values:self.pxMode=bool(values['pxMode'])
        self.changed()
    def setVisible(self,value):self.visible=bool(value);self.changed()
    def setTransform(self,matrix):self.matrix=matrix;self.changed()
    def setDepthValue(self,value):self.depth=value;self.changed()
    def setGLOptions(self,value):
        if isinstance(value,dict):self.depth_test=bool(value.get(int(G.GL_DEPTH_TEST),True))
        self.changed()
    def paint(self):pass
    def upload(self):
        if self.buffer is None:
            self.buffer=self.owner.create_buffer() if hasattr(self.owner,'create_buffer') else QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.Type.VertexBuffer)
            if not self.buffer.create():raise RuntimeError('GLES vertex buffer allocation failed')
        n=len(self.pos);colors=np.asarray(self.color,np.float32)
        if colors.ndim==1:colors=np.broadcast_to(colors,(n,len(colors)))
        if len(colors)!=n:raise ValueError('Point/color count mismatch')
        if colors.shape[1]==3:colors=np.c_[colors,np.ones(n,np.float32)]
        data=np.ascontiguousarray(np.c_[self.pos,colors],np.float32)
        self.buffer.bind();raw=data.tobytes();self.buffer.allocate(raw,len(raw));self.count=n;self.dirty=False
        self.owner.uploads+=1;self.owner.upload_bytes+=len(raw)


class GLScatterPlotItem(Item):pass
class GLLinePlotItem(Item):
    primitive=G.GL_LINES
    def __init__(self,width=1,mode='lines',**values):
        self.width=width
        if mode=='line_strip':self.primitive=G.GL_LINE_STRIP
        super().__init__(**values)


class GLGridItem(GLLinePlotItem):
    def __init__(self):
        self.extent=(10,10);self.spacing=(1,1);super().__init__(color=(.2,.3,.4,.5));self.rebuild()
    def setSize(self,x,y):self.extent=(x,y);self.rebuild()
    def setSpacing(self,x,y):self.spacing=(x,y);self.rebuild()
    def setColor(self,color):self.color=np.asarray(color,np.float32)/255.;self.dirty=True;self.changed()
    def rebuild(self):
        x,y=self.extent;sx,sy=self.spacing;lines=[]
        for p in np.arange(-x/2,x/2+sx/2,max(sx,1e-8))[:200]:lines.extend(((p,-y/2,0),(p,y/2,0)))
        for p in np.arange(-y/2,y/2+sy/2,max(sy,1e-8))[:200]:lines.extend(((-x/2,p,0),(x/2,p,0)))
        self.setData(pos=np.asarray(lines,np.float32))


class GLAxisItem(GLLinePlotItem):
    def __init__(self):super().__init__();self.setSize(1,1,1)
    def setSize(self,x,y,z):
        self.setData(pos=np.array([[0,0,0],[x,0,0],[0,0,0],[0,y,0],[0,0,0],[0,0,z]],np.float32),
                     color=np.array([[1,.2,.2,1]]*2+[[.2,1,.2,1]]*2+[[.2,.4,1,1]]*2,np.float32))


class _Surface(QtOpenGL.QOpenGLWindow):
    # Native EGL swapchain: no QOpenGLWidget FBO or QWidget backing-store
    # composition. Each independent map owns its shader, VAO and buffers.
    def __init__(self,owner):
        super().__init__();self.owner=owner
        self.setFlags(QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|QtCore.Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setTitle('ORB 3D · Mali')
    def setWindowFlags(self,flags):self.setFlags(flags)
    def setWindowTitle(self,title):self.setTitle(title)
    def initializeGL(self):self.owner.initializeGL()
    def paintGL(self):self.owner.paintGL()
    def mousePressEvent(self,event):self.owner.interacted.emit();self.owner.mousePressEvent(event)
    def mouseMoveEvent(self,event):self.owner.mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):self.owner.mouseReleaseEvent(event)
    def wheelEvent(self,event):self.owner.interacted.emit();self.owner.wheelEvent(event)


class GLViewWidget(QtWidgets.QWidget):
    interacted=QtCore.Signal()
    def __init__(self):
        super().__init__();self.items=[];self.background=QtGui.QColor('#0a1421')
        self.opts=dict(distance=8.,elevation=25.,azimuth=-60.,center=QtGui.QVector3D(),fov=60.)
        self.mouse=None;self.program=None;self.vao=None;self.uploads=0;self.upload_bytes=0;self.renderer={}
        self.paint_ms=deque(maxlen=600);self.paint_times=deque(maxlen=600)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.surface=_Surface(self)
        self.last_geometry=None
        self.detached=False
        self.position_timer=QtCore.QTimer(self);self.position_timer.setInterval(80)
        self.position_timer.timeout.connect(self.sync_surface);self.position_timer.start()
    def sync_surface(self):
        if self.detached:return
        if not self.isVisible() or self.window().isMinimized():
            self.surface.hide();return
        rect=QtCore.QRect(self.mapToGlobal(QtCore.QPoint(0,0)),self.size())
        key=(rect.x(),rect.y(),rect.width(),rect.height())
        if key!=self.last_geometry:self.surface.setGeometry(rect);self.last_geometry=key
        if not self.surface.isVisible():
            self.surface.show()
            if self.window().windowHandle():
                self.surface.setTransientParent(self.window().windowHandle())
    def detach(self,title,rectangle):
        self.detached=True
        self.surface.setWindowFlags(QtCore.Qt.WindowType.Window|QtCore.Qt.WindowType.WindowTitleHint|QtCore.Qt.WindowType.WindowMinMaxButtonsHint|QtCore.Qt.WindowType.WindowCloseButtonHint)
        self.surface.setWindowTitle(title);self.surface.setGeometry(rectangle);self.surface.show()
    def setWindowTitle(self,title):
        super().setWindowTitle(title)
        if hasattr(self,'surface'):self.surface.setTitle(title)
    def width(self):return self.surface.width() if getattr(self,'detached',False) else super().width()
    def height(self):return self.surface.height() if getattr(self,'detached',False) else super().height()
    def hideEvent(self,event):
        if not self.detached:self.surface.hide()
        super().hideEvent(event)
    def showEvent(self,event):super().showEvent(event);QtCore.QTimer.singleShot(0,self.sync_surface)
    def resizeEvent(self,event):super().resizeEvent(event);QtCore.QTimer.singleShot(0,self.sync_surface)
    def context(self):return self.surface.context()
    def makeCurrent(self):return self.surface.makeCurrent()
    def doneCurrent(self):return self.surface.doneCurrent()
    def update(self,*unused):
        if hasattr(self,'surface'):self.surface.update()
        super().update()
    def grabFramebuffer(self):return self.surface.grabFramebuffer()
    def setBackgroundColor(self,color):self.background=QtGui.QColor(color);self.update()
    def addItem(self,item):
        if item.owner is not None:raise ValueError('3D item already has an owner')
        item.owner=self;self.items.append(item);self.update()
    def removeItem(self,item):
        if item not in self.items:return
        if item.buffer is not None and self.context() and self.context().isValid():
            self.makeCurrent();item.buffer.destroy();item.buffer=None;self.doneCurrent()
        self.items.remove(item);item.owner=None;self.update()
    def setCameraPosition(self,pos=None,distance=None,elevation=None,azimuth=None):
        if pos is not None:self.opts['center']=QtGui.QVector3D(float(pos.x()),float(pos.y()),float(pos.z()))
        for key,value in (('distance',distance),('elevation',elevation),('azimuth',azimuth)):
            if value is not None:self.opts[key]=float(value)
        self.update()
    def getViewport(self):return (0,0,self.width(),self.height())
    def viewMatrix(self):
        o=self.opts;az=math.radians(o['azimuth']);el=math.radians(o['elevation']);d=o['distance']
        delta=QtGui.QVector3D(d*math.cos(el)*math.cos(az),d*math.cos(el)*math.sin(az),d*math.sin(el))
        matrix=QtGui.QMatrix4x4();matrix.lookAt(o['center']+delta,o['center'],QtGui.QVector3D(0,0,1));return matrix
    def projectionMatrix(self,*unused):
        o=self.opts;aspect=max(1,self.width())/max(1,self.height())
        vertical=math.degrees(2*math.atan(math.tan(math.radians(o['fov'])/2)/aspect))
        matrix=QtGui.QMatrix4x4();matrix.perspective(vertical,aspect,max(o['distance']*.0001,1e-5),max(100.,o['distance']*1000));return matrix
    def initializeGL(self):
        try:
            def name(key):
                value=G.glGetString(key)
                return value.decode() if isinstance(value,bytes) else ctypes.cast(value,ctypes.c_char_p).value.decode()
            self.renderer=dict(vendor=name(G.GL_VENDOR),renderer=name(G.GL_RENDERER),version=name(G.GL_VERSION))
            print('ORB_GPU '+str(self.renderer),flush=True)
            if 'mali' not in self.renderer['renderer'].lower():
                raise RuntimeError('Hardware renderer required; got '+self.renderer['renderer'])
            program=QtOpenGL.QOpenGLShaderProgram(self)
            for kind,source in ((QtOpenGL.QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),(QtOpenGL.QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)):
                if not program.addShaderFromSourceCode(kind,source):raise RuntimeError(program.log())
            if not program.link():raise RuntimeError(program.log())
            self.program=program
            self.vao=QtOpenGL.QOpenGLVertexArrayObject(self)
            if not self.vao.create():raise RuntimeError('GLES vertex array allocation failed')
            self.uniforms={name:int(G.glGetUniformLocation(program.programId(),name.encode()))
                           for name in ('view','projection','viewport_height','model','size','pixel_size','points')}
            self.context().aboutToBeDestroyed.connect(self.release)
        except Exception as exc:
            print('ORB_GPU_FAILED '+str(exc),flush=True);QtCore.QTimer.singleShot(0,lambda:QtWidgets.QApplication.exit(2))
    def release(self):
        self.makeCurrent()
        for item in self.items:
            if item.buffer is not None:item.buffer.destroy();item.buffer=None;item.dirty=True
        if self.vao is not None:self.vao.destroy()
        self.doneCurrent()
    def paintGL(self):
        if self.program is None:return
        G.glBindFramebuffer(G.GL_FRAMEBUFFER,self.surface.defaultFramebufferObject())
        began=time.perf_counter();ratio=self.devicePixelRatioF();G.glViewport(0,0,int(self.width()*ratio),int(self.height()*ratio))
        c=self.background;G.glClearColor(c.redF(),c.greenF(),c.blueF(),1);G.glClear(G.GL_COLOR_BUFFER_BIT|G.GL_DEPTH_BUFFER_BIT)
        G.glEnable(G.GL_BLEND);G.glBlendFunc(G.GL_SRC_ALPHA,G.GL_ONE_MINUS_SRC_ALPHA)
        self.vao.bind();p=self.program
        if not p.bind():raise RuntimeError('GLES shader bind failed: '+p.log())
        u=self.uniforms
        G.glUniformMatrix4fv(u['view'],1,False,np.asarray(self.viewMatrix().data(),np.float32))
        G.glUniformMatrix4fv(u['projection'],1,False,np.asarray(self.projectionMatrix().data(),np.float32))
        G.glUniform1f(u['viewport_height'],float(self.height()*ratio));p.enableAttributeArray(0);p.enableAttributeArray(1)
        for item in sorted(self.items,key=lambda i:i.depth):
            if not item.visible or not len(item.pos):continue
            if item.depth_test:G.glEnable(G.GL_DEPTH_TEST)
            else:G.glDisable(G.GL_DEPTH_TEST)
            G.glDepthMask(bool(item.depth_test))
            if item.dirty:item.upload()
            else:item.buffer.bind()
            p.setAttributeBuffer(0,int(G.GL_FLOAT),0,3,28);p.setAttributeBuffer(1,int(G.GL_FLOAT),12,4,28)
            G.glUniformMatrix4fv(u['model'],1,False,np.asarray(item.matrix.data(),np.float32))
            G.glUniform1f(u['size'],float(item.size))
            G.glUniform1i(u['pixel_size'],int(item.pxMode));G.glUniform1i(u['points'],int(item.primitive==G.GL_POINTS))
            if item.primitive!=G.GL_POINTS:G.glLineWidth(1.)
            G.glDrawArrays(item.primitive,0,item.count)
        G.glDepthMask(True);p.disableAttributeArray(0);p.disableAttributeArray(1);p.release();self.vao.release()
        self.paint_times.append(time.perf_counter());self.paint_ms.append((time.perf_counter()-began)*1000)
    def renderer_status(self):
        times=list(self.paint_times)
        return dict(self.renderer,paints=len(times),fps=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0,
                    paint_cpu_ms_p95=float(np.percentile(self.paint_ms,95)) if self.paint_ms else 0,
                    uploads=self.uploads,upload_bytes=self.upload_bytes,point_size_cap_px=3)
    def mousePressEvent(self,event):self.mouse=event.position()
    def mouseMoveEvent(self,event):
        if self.mouse is None:return
        current=event.position();dx=current.x()-self.mouse.x();dy=current.y()-self.mouse.y();self.mouse=current
        if event.buttons()&QtCore.Qt.MouseButton.LeftButton:
            self.opts['azimuth']-=dx*.5;self.opts['elevation']=max(-89.9,min(89.9,self.opts['elevation']+dy*.5))
        elif event.buttons()&(QtCore.Qt.MouseButton.MiddleButton|QtCore.Qt.MouseButton.RightButton):
            matrix=self.viewMatrix().inverted()[0];right=matrix.mapVector(QtGui.QVector3D(1,0,0));up=matrix.mapVector(QtGui.QVector3D(0,1,0))
            scale=2*self.opts['distance']*math.tan(math.radians(self.opts['fov'])/2)/max(1,self.width())
            self.opts['center']+=right*(-dx*scale)+up*(dy*scale)
        self.update()
    def mouseReleaseEvent(self,event):self.mouse=None
    def wheelEvent(self,event):
        self.opts['distance']=max(.0001,min(1e7,self.opts['distance']*math.exp(-event.angleDelta().y()*.0015)))
        self.update();event.accept()
