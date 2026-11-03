"""Portable file/tensor contract shared by reference and KV260 workers."""
import hashlib
import json
import os
from pathlib import Path
import re
from contextlib import contextmanager
import numpy as np

INPUT_SHAPE = (1, 3, 256, 256)
OUTPUT_SHAPE = (256, 256)


@contextmanager
def output_lock(folder):
    """OS-owned lock releases on process crash; never treats a stale PID as an owner."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stream=(folder/'.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close();raise RuntimeError('Output directory already has a running owner')
    try:yield
    finally:stream.close()

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024), b''): h.update(data)
    return h.hexdigest()

def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.part')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temp,path)

def checked_id(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',name):raise ValueError('Unsafe frame ID')
    return name

def read_tensor(path,shape):
    path=Path(path)
    if path.stat().st_size!=int(np.prod(shape))*4:raise ValueError('Tensor byte count mismatch: '+str(path))
    value=np.fromfile(path,dtype='<f4').reshape(shape)
    if not np.isfinite(value).all():raise ValueError('Nonfinite tensor: '+str(path))
    return value

def write_tensor(path,value,shape=OUTPUT_SHAPE):
    value=np.asarray(value,dtype='<f4')
    if value.shape!=tuple(shape) or not np.isfinite(value).all():raise ValueError('Output shape/nonfinite error')
    path=Path(path);temp=path.with_name(path.name+'.part');value.tofile(temp);os.replace(temp,path)

def preprocess(rgb):
    import cv2
    if rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.dtype!=np.uint8:raise ValueError('Expected uint8 RGB')
    resized=cv2.resize(rgb,(256,256),interpolation=cv2.INTER_CUBIC)
    x=(resized.astype(np.float32)/255.-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    return np.ascontiguousarray(x.transpose(2,0,1)[None])

def load_midas(assets,static_padding=False):
    import torch
    import sys
    assets=Path(assets).resolve()
    if str(assets/'midas-v21') not in sys.path:sys.path.insert(0,str(assets/'midas-v21'))
    import midas.blocks
    from midas.midas_net_custom import MidasNet_small
    def backbone(pretrained,exportable=False):
        if pretrained:raise ValueError('Implicit backbone download is forbidden')
        net=torch.hub.load(str(assets/'gen-efficientnet'),'tf_efficientnet_lite3',source='local',pretrained=False,exportable=exportable)
        return midas.blocks._make_efficientnet_backbone(net)
    midas.blocks._make_pretrained_efficientnet_lite3=backbone
    weight=assets/'midas_v21_small_256.pt'
    if digest(weight)!='70d6b9c891758c67f974a6097fb0c608c7ee67fb81ac3e5588847d5596d56fca':raise ValueError('MiDaS weight SHA mismatch')
    model=MidasNet_small(str(weight),features=64,backbone='efficientnet_lite3',exportable=True,non_negative=True,blocks={'expand':True}).eval()
    if static_padding:freeze_same_padding(model)
    return model


def freeze_same_padding(model):
    """Fold only shape-dependent SAME padding for the fixed 256x256 domain."""
    import torch
    shapes={};hooks=[]
    for name,layer in model.named_modules():
        if type(layer).__name__=='Conv2dSame':
            def hook(module,args,output,key=name):shapes[key]=tuple(args[0].shape[-2:])
            hooks.append(layer.register_forward_hook(hook))
    with torch.no_grad():model(torch.zeros(INPUT_SHAPE))
    for hook in hooks:hook.remove()
    for name,(h,w) in shapes.items():
        parts=name.split('.');parent=model
        for part in parts[:-1]:parent=getattr(parent,part)
        old=getattr(parent,parts[-1]);kh,kw=old.kernel_size;sh,sw=old.stride;dh,dw=old.dilation
        ph=max(((h+sh-1)//sh-1)*sh+(kh-1)*dh+1-h,0)
        pw=max(((w+sw-1)//sw-1)*sw+(kw-1)*dw+1-w,0)
        conv=torch.nn.Conv2d(old.in_channels,old.out_channels,old.kernel_size,old.stride,0,old.dilation,old.groups,old.bias is not None)
        conv.weight=old.weight;conv.bias=old.bias
        fixed=torch.nn.Sequential(torch.nn.ZeroPad2d((pw//2,pw-pw//2,ph//2,ph-ph//2)),conv)
        setattr(parent,parts[-1],fixed)
    model.eval()
