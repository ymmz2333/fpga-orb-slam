"""Mali-400-compatible GLES2 renderer; Qt resolves functions for the actual context."""
import time
import os
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets,QtOpenGL
import gles_view as base

GLScatterPlotItem=base.GLScatterPlotItem
GLLinePlotItem=base.GLLinePlotItem
GLGridItem=base.GLGridItem
GLAxisItem=base.GLAxisItem
G=base.G

VERTEX='''#version 100
precision highp float;
attribute vec3 position;
attribute vec4 color;
uniform mat4 model,view,projection;
uniform float size,viewport_height;
uniform bool pixel_size;
varying vec4 rgba;
void main(){
 vec4 p=view*model*vec4(position,1.0);
 gl_Position=projection*p;
 float d=pixel_size?size:size*viewport_height*projection[1][1]/max(0.00001,-p.z);
 gl_PointSize=clamp(d,1.0,3.0);rgba=color;
}'''
FRAGMENT='''#version 100
precision mediump float;
varying vec4 rgba;
uniform bool points;
void main(){
 if(points){vec2 d=gl_PointCoord-vec2(0.5);if(dot(d,d)>0.25)discard;}
 gl_FragColor=rgba;
}'''


def configure():
    fmt=QtGui.QSurfaceFormat();fmt.setRenderableType(QtGui.QSurfaceFormat.RenderableType.OpenGLES)
    fmt.setVersion(2,0);fmt.setDepthBufferSize(24);fmt.setSwapInterval(1)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)


class GLViewWidget(base.GLViewWidget):
    def release(self):
        # QOpenGLWindow may emit context destruction after its QWidget owner has
        # begun teardown. Only call into still-live Qt objects.
        from shiboken6 import isValid
        if not isValid(self.surface):return
        context=self.surface.context()
        if context is None or not isValid(context):return
        self.surface.makeCurrent()
        try:
            for item in self.items:
                if item.buffer is not None and isValid(item.buffer):item.buffer.destroy()
                item.buffer=None;item.dirty=True
        finally:self.surface.doneCurrent()

    def initializeGL(self):
        try:
            self.functions=self.context().functions();self.functions.initializeOpenGLFunctions()
            def name(key):
                value=self.functions.glGetString(int(key))
                return value.decode() if isinstance(value,bytes) else str(value)
            self.renderer=dict(vendor=name(G.GL_VENDOR),renderer=name(G.GL_RENDERER),version=name(G.GL_VERSION),api='OpenGL ES 2.0 compatible')
            self.renderer['software']=any(x in self.renderer['renderer'].lower() for x in ('llvmpipe','softpipe','software'))
            print('KV260_GUI_RENDERER '+str(self.renderer),flush=True)
            if self.renderer['software'] and os.getenv('ORB60_GUI_QA_SOFTWARE')!='1':
                raise RuntimeError('Hardware GPU rendering required; software rendering is allowed only in an explicit QA run')
            program=QtOpenGL.QOpenGLShaderProgram(self)
            for kind,source in ((QtOpenGL.QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),(QtOpenGL.QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)):
                if not program.addShaderFromSourceCode(kind,source):raise RuntimeError(program.log())
            program.bindAttributeLocation('position',0);program.bindAttributeLocation('color',1)
            if not program.link():raise RuntimeError(program.log())
            self.program=program
            self.uniforms={name:program.uniformLocation(name) for name in ('view','projection','viewport_height','model','size','pixel_size','points')}
            self.context().aboutToBeDestroyed.connect(self.release)
        except Exception as exc:
            print('KV260_GUI_RENDERER_FAILED '+str(exc),flush=True)
            QtCore.QTimer.singleShot(0,lambda:QtWidgets.QApplication.exit(2))

    def paintGL(self):
        if self.program is None:return
        gl=self.functions;began=time.perf_counter();ratio=self.devicePixelRatioF()
        gl.glBindFramebuffer(int(G.GL_FRAMEBUFFER),self.surface.defaultFramebufferObject())
        gl.glViewport(0,0,int(self.width()*ratio),int(self.height()*ratio))
        color=self.background;gl.glClearColor(color.redF(),color.greenF(),color.blueF(),1.)
        gl.glClear(int(G.GL_COLOR_BUFFER_BIT|G.GL_DEPTH_BUFFER_BIT))
        gl.glEnable(int(G.GL_BLEND));gl.glBlendFunc(int(G.GL_SRC_ALPHA),int(G.GL_ONE_MINUS_SRC_ALPHA))
        program=self.program
        if not program.bind():raise RuntimeError('GLES2 shader bind failed: '+program.log())
        u=self.uniforms
        program.setUniformValue(u['view'],self.viewMatrix());program.setUniformValue(u['projection'],self.projectionMatrix())
        program.setUniformValue(u['viewport_height'],float(self.height()*ratio))
        program.enableAttributeArray(0);program.enableAttributeArray(1)
        for item in sorted(self.items,key=lambda i:i.depth):
            if not item.visible or not len(item.pos):continue
            (gl.glEnable if item.depth_test else gl.glDisable)(int(G.GL_DEPTH_TEST));gl.glDepthMask(bool(item.depth_test))
            if item.dirty:item.upload()
            else:item.buffer.bind()
            program.setAttributeBuffer(0,int(G.GL_FLOAT),0,3,28);program.setAttributeBuffer(1,int(G.GL_FLOAT),12,4,28)
            program.setUniformValue(u['model'],item.matrix);program.setUniformValue(u['size'],float(item.size))
            program.setUniformValue(u['pixel_size'],bool(item.pxMode));program.setUniformValue(u['points'],item.primitive==G.GL_POINTS)
            if item.primitive!=G.GL_POINTS:gl.glLineWidth(1.)
            gl.glDrawArrays(int(item.primitive),0,item.count)
        gl.glDepthMask(True);program.disableAttributeArray(0);program.disableAttributeArray(1);program.release()
        self.paint_times.append(time.perf_counter());self.paint_ms.append((time.perf_counter()-began)*1000)
