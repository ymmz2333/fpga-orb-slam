"""Read-only visualization wire format. All arrays retain SLAM coordinates."""
import json
import struct
import zlib
from dataclasses import dataclass
import numpy as np

HEADER=struct.Struct('<8s6I')
MAX_META=256*1024
MAX_JPEG=4*1024*1024
MAX_POINTS=20000
MAX_KEYFRAMES=2000
POINT_DTYPE=np.dtype([('id','<u8'),('xyz','<f4',(3,))])
KEYFRAME_DTYPE=np.dtype([('id','<u8'),('twc','<f4',(4,4))])


def body_size(header):
    magic,version,meta,jpeg,points,keys,_=HEADER.unpack(header)
    if magic!=b'ORBVIZ01' or version!=1:raise ValueError('不支持的可视化协议')
    if not 2<=meta<=MAX_META or jpeg>MAX_JPEG or points>MAX_POINTS or keys>MAX_KEYFRAMES:
        raise ValueError('可视化包长度超限')
    return meta+jpeg+points*POINT_DTYPE.itemsize+keys*KEYFRAME_DTYPE.itemsize


@dataclass
class Snapshot:
    meta:dict
    jpeg:bytes
    points:np.ndarray
    keyframes:np.ndarray
    wire:bytes

    @classmethod
    def decode(cls,packet):
        if len(packet)<HEADER.size:raise ValueError('可视化包头不完整')
        header=packet[:32];size=body_size(header)
        if len(packet)!=size+32:raise ValueError('可视化包正文不完整')
        _,_,meta_n,jpeg_n,points_n,key_n,crc=HEADER.unpack(header);body=packet[32:]
        if zlib.crc32(body)!=crc:raise ValueError('可视化包CRC错误')
        def invalid_constant(_):raise ValueError('非有限JSON数字')
        meta=json.loads(body[:meta_n],parse_constant=invalid_constant)
        if not isinstance(meta,dict):raise ValueError('无效元数据')
        start=meta_n+jpeg_n
        points=np.frombuffer(body,dtype=POINT_DTYPE,count=points_n,offset=start)
        keyframes=np.frombuffer(body,dtype=KEYFRAME_DTYPE,count=key_n,offset=start+points_n*20)
        if not np.isfinite(points['xyz']).all() or not np.isfinite(keyframes['twc']).all():
            raise ValueError('非有限三维数据')
        if meta.get('event')!='status':
            if (meta.get('width'),meta.get('height'))!=(960,720):raise ValueError('输入分辨率不匹配')
            features=np.asarray(meta.get('features',[]),dtype=np.float32).reshape(-1,4)
            if len(features)>1000 or not np.isfinite(features).all():raise ValueError('特征数据超限')
            if len(features) and ((features[:,0]<0).any() or (features[:,0]>=960).any() or
                                  (features[:,1]<0).any() or (features[:,1]>=720).any()):raise ValueError('特征坐标越界')
            if len(features)!=meta.get('feature_count'):raise ValueError('特征数量不匹配')
            pose=np.asarray(meta.get('pose_twc'),dtype=np.float32)
            if pose.shape!=(16,) or not np.isfinite(pose).all():raise ValueError('位姿无效')
        return cls(meta,body[meta_n:meta_n+jpeg_n],points,keyframes,bytes(packet))


def status_packet(state):
    body=json.dumps(dict(event='status',session_state=state),ensure_ascii=False).encode('utf-8')
    return HEADER.pack(b'ORBVIZ01',1,len(body),0,0,0,zlib.crc32(body))+body


def receive(sock,size):
    data=bytearray(size);view=memoryview(data);at=0
    while at<size:
        n=sock.recv_into(view[at:])
        if not n:raise ConnectionError('可视化连接已关闭')
        at+=n
    return bytes(data)


def receive_snapshot(sock):
    header=receive(sock,32)
    return Snapshot.decode(header+receive(sock,body_size(header)))
