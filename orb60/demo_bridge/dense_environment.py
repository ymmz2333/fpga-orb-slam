"""Bounded display-only cloud bound to exact sparse geometry and calibration."""
import hashlib
from pathlib import Path
import struct
import zlib
import numpy as np

POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])


def write(path,xyz,rgb,points_csv,camera_csv):
    xyz=np.asarray(xyz,dtype='<f4');rgb=np.asarray(rgb,dtype=np.uint8)
    if xyz.ndim!=2 or xyz.shape[1]!=3 or rgb.shape!=xyz.shape or not 1<=len(xyz)<=2000000 or not np.isfinite(xyz).all():
        raise ValueError('Invalid bounded dense environment')
    data=np.empty(len(xyz),POINT);data['xyz']=xyz;data['rgb']=rgb;payload=data.tobytes()
    header=b'ORBDNS01'+struct.pack('<I',len(xyz))
    header+=hashlib.sha256(Path(points_csv).read_bytes()).hexdigest().encode()
    header+=hashlib.sha256(Path(camera_csv).read_bytes()).hexdigest().encode()
    header+=struct.pack('<I',zlib.crc32(payload))
    Path(path).write_bytes(header+payload)


def validate(path,points_csv,camera_csv):
    data=Path(path).read_bytes()
    if len(data)<144 or data[:8]!=b'ORBDNS01':raise ValueError('Invalid dense header')
    n=struct.unpack_from('<I',data,8)[0]
    if not 1<=n<=2000000 or len(data)!=144+n*15:raise ValueError('Dense capacity/size mismatch')
    if data[12:76]!=hashlib.sha256(Path(points_csv).read_bytes()).hexdigest().encode() or data[76:140]!=hashlib.sha256(Path(camera_csv).read_bytes()).hexdigest().encode():
        raise ValueError('Dense/sparse/calibration mismatch')
    if struct.unpack_from('<I',data,140)[0]!=zlib.crc32(data[144:]):raise ValueError('Dense CRC mismatch')
    points=np.frombuffer(data,POINT,offset=144)
    if not np.isfinite(points['xyz']).all():raise ValueError('Nonfinite dense point')
    return n
