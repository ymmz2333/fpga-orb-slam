"""Independent double precision geometry oracle and explicit packed ABI."""
import numpy as np

MAX_SAMPLES=172800
MAGIC=0x50434c31

def configuration(k,twc):
    from orb60.dense.geometry import valid_pose
    k=np.asarray(k,float);twc=np.asarray(twc,float)
    if k.shape!=(3,3) or not np.isfinite(k).all() or not valid_pose(twc):
        raise ValueError('Finite invertible camera matrix and valid Twc required')
    out=np.zeros(24,'<f4');out[:9]=np.linalg.inv(k).ravel();out[9:21]=twc[:3].ravel()
    if not np.isfinite(out).all():raise ValueError('Configuration cannot be represented by FP32')
    return out

def samples(depth,rgb,mask,stride=2):
    depth=np.asarray(depth);rgb=np.asarray(rgb);mask=np.asarray(mask)
    if depth.shape!=(720,960) or rgb.shape!=(720,960,3) or rgb.dtype!=np.uint8 or mask.shape!=depth.shape:
        raise ValueError('Paired 960x720 depth, RGB and mask required')
    if type(stride)!=int or stride<2 or stride>16:raise ValueError('Stride must be integer2..16')
    yy,xx=np.mgrid[0:720:stride,0:960:stride]
    out=np.zeros((xx.size,4),'<u4');out[:,0]=np.ascontiguousarray(depth[yy,xx],dtype='<f4').ravel().view('<u4')
    color=rgb[yy,xx].reshape(-1,3).astype(np.uint32)
    out[:,1]=color[:,0]|color[:,1]<<8|color[:,2]<<16
    out[:,2]=xx.ravel().astype(np.uint32)|yy.ravel().astype(np.uint32)<<16
    out[:,3]=mask[yy,xx].ravel().astype(bool)
    return out

def golden(data,config,count=None,capacity=MAX_SAMPLES):
    data=np.asarray(data,dtype='<u4');config=np.asarray(config,dtype='<f4');count=len(data) if count is None else count
    stats=np.array([0,0,0,0,MAGIC,1,0,0],'<u4')
    if not 0<=count<=MAX_SAMPLES or not 0<=capacity<=MAX_SAMPLES:stats[3]=2;return np.zeros((0,8),'<u4'),stats
    if config.shape!=(24,) or not np.isfinite(config[:21]).all():stats[3]=4;return np.zeros((0,8),'<u4'),stats
    if count>len(data):raise ValueError('Truncated samples')
    data=data[:count];u=data[:,2]&65535;v=data[:,2]>>16;z=data[:,0].copy().view('<f4').astype(float)
    good=(data[:,3]&1!=0)&(u<960)&(v<720)&np.isfinite(z)&(z>0)
    with np.errstate(invalid='ignore',over='ignore'):
        local=(np.c_[u,v,np.ones(count)]@config[:9].astype(float).reshape(3,3).T)*z[:,None]
        pose=config[9:21].astype(float).reshape(3,4)
        world=local@pose[:,:3].T+pose[:,3]
        xyz=np.c_[local,world].astype('<f4')
    good &= np.isfinite(xyz).all(axis=1)
    ids=np.flatnonzero(good);n=min(len(ids),capacity);chosen=ids[:n]
    out=np.zeros((n,8),'<u4');out[:,:6]=xyz[chosen].copy().view('<u4')
    out[:,6]=data[chosen,1]&0xffffff;out[:,7]=(v[chosen]*960+u[chosen])
    stats[:4]=[count,len(ids),n,int(len(ids)>capacity)]
    return out,stats

def compare(actual,expected):
    actual=np.asarray(actual,dtype='<u4').reshape(-1,8);expected=np.asarray(expected,dtype='<u4').reshape(-1,8)
    if actual.shape!=expected.shape or not np.array_equal(actual[:,6:],expected[:,6:]):raise AssertionError('Point count, color, order or source index differs')
    if not np.allclose(actual[:,:6].copy().view('<f4'),expected[:,:6].copy().view('<f4'),rtol=3e-5,atol=3e-5,equal_nan=False):
        raise AssertionError('PL geometry exceeds documented FP32 tolerance')
