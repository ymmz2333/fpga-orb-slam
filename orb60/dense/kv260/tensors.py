"""Explicit PS tensor work; never substitute CPU convolution for a DPU."""
import numpy as np

def quantize(value,fix_point):
    # Vitis AI DPU round: nearest, with half ties toward +infinity.
    scaled=np.asarray(value,dtype=np.float64)*2.**int(fix_point)
    if not np.isfinite(scaled).all():raise ValueError('Nonfinite quantization input')
    return np.clip(np.floor(scaled+.5),-128,127).astype(np.int8)

def dequantize(value,fix_point):return np.asarray(value,dtype=np.float32)*2.**(-int(fix_point))


def pack_input(x,shape,dtype,fix_point=None):
    x=np.asarray(x)
    if x.shape!=(1,3,256,256) or not np.isfinite(x).all():raise ValueError('External RGB tensor contract mismatch')
    value=to_nhwc(x) if tuple(shape)==(1,256,256,3) else x
    if value.shape!=tuple(shape):raise ValueError('Unexpected DPU input layout')
    if np.dtype(dtype)==np.int8:
        if fix_point is None:raise ValueError('Missing input quantization fix_point')
        return quantize(value,fix_point)
    if np.dtype(dtype)!=np.float32:raise ValueError('Unsupported DPU boundary dtype')
    return value


def unpack_output(value,fix_point=None):
    value=np.asarray(value)
    if tuple(value.shape) not in {(1,256,256,1),(1,1,256,256),(1,256,256),(256,256)}:raise ValueError('Unexpected DPU output layout')
    if value.dtype==np.int8:
        if fix_point is None:raise ValueError('Missing output quantization fix_point')
        value=dequantize(value,fix_point)
    elif value.dtype!=np.float32:raise ValueError('Unsupported output dtype')
    if not np.isfinite(value).all():raise ValueError('Nonfinite DPU output')
    return value.copy().reshape(256,256)

def resize_nchw(value,size,align_corners):
    """Independent float32 bilinear reference for MiDaS PS Resize operations."""
    x=np.asarray(value,dtype=np.float32)
    if x.ndim!=4 or min(size)<1 or not np.isfinite(x).all():raise ValueError('Invalid Resize tensor')
    h,w=x.shape[-2:];oh,ow=map(int,size)
    def positions(n,m):
        if align_corners:return np.arange(m,dtype=np.float64)*(n-1)/max(m-1,1)
        return np.maximum((np.arange(m,dtype=np.float64)+.5)*n/m-.5,0)
    yy,xx=positions(h,oh),positions(w,ow);y0=np.floor(yy).astype(int);x0=np.floor(xx).astype(int)
    y1=np.minimum(y0+1,h-1);x1=np.minimum(x0+1,w-1)
    fy=(yy-y0).astype(np.float32)[None,None,:,None];fx=(xx-x0).astype(np.float32)[None,None,None,:]
    top=x[:,:,y0[:,None],x0[None,:]]*(1-fx)+x[:,:,y0[:,None],x1[None,:]]*fx
    bottom=x[:,:,y1[:,None],x0[None,:]]*(1-fx)+x[:,:,y1[:,None],x1[None,:]]*fx
    return top*(1-fy)+bottom*fy

def to_nhwc(x):
    if np.asarray(x).ndim!=4:raise ValueError('Expected NCHW')
    return np.ascontiguousarray(np.transpose(x,(0,2,3,1)))

def to_nchw(x):
    if np.asarray(x).ndim!=4:raise ValueError('Expected NHWC')
    return np.ascontiguousarray(np.transpose(x,(0,3,1,2)))
