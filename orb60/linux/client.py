"""ORB60 wire codec and PC client. Raw PL records are never CPU-ORB records."""
import argparse
import json
from pathlib import Path
import socket
import struct
import time
import zlib

HEADER=struct.Struct('<8sHHIQQ8I')
WIDTHS=(960,800,667,556,463,386,322,268)
HEIGHTS=(720,600,500,417,347,289,241,201)
BUDGETS=(217,181,151,126,105,87,73,60)
CAPACITY=1000


def require(ok,message):
    if not ok:
        raise ValueError(message)


def receive(sock,size):
    result=bytearray()
    while len(result)<size:
        part=sock.recv(size-len(result))
        if not part:
            raise ConnectionError('short ORB60 reply')
        result.extend(part)
    return bytes(result)


def request_header(frame_id,timestamp_ns,role,pixels):
    require(len(pixels)==960*720,'expected GRAY8 960x720')
    require(role in (0,1) and timestamp_ns>0,'invalid role/timestamp')
    return HEADER.pack(b'ORB60NET',1,64,1,frame_id,timestamp_ns,960,720,role,CAPACITY,
                       len(pixels),0,zlib.crc32(pixels),0)


def decode(header,payload,frame_id,timestamp_ns,role,allow_simulated=False):
    magic,version,header_bytes,kind,fid,ts,w,h,r,count,n,status,crc,flags=HEADER.unpack(header)
    require((magic,version,header_bytes,kind,fid,ts,w,h,r)==
            (b'ORB60NET',1,64,2,frame_id,timestamp_ns,960,720,role),'reply identity/version mismatch')
    require(n==len(payload) and n<=65152,'reply length out of bounds')
    require(zlib.crc32(payload)==crc,'reply CRC mismatch')
    require(status==0,'board error {}: {}'.format(status,payload.decode('utf-8',errors='replace')))
    require(flags==0 or (allow_simulated and flags==1),'simulated/unknown backend refused')
    require(count<=CAPACITY and len(payload)==128+count*64+1024,'feature capacity/length mismatch')
    counts=struct.unpack_from('<8I',payload)
    offsets=struct.unpack_from('<8I',payload,32)
    total=0
    for level,(num,offset) in enumerate(zip(counts,offsets)):
        require(offset==total and num<=BUDGETS[level],'per-level append layout mismatch')
        total+=num
    require(total==count and payload[80:128]==bytes(48),'count/reserved mismatch')
    stats=payload[128+count*64:]
    records=payload[128:128+count*64]
    for level,(num,offset) in enumerate(zip(counts,offsets)):
        if not flags:
            layer=struct.unpack_from('<16I',stats,level*128)
            desc=struct.unpack_from('<16I',stats,level*128+64)
            require(layer[:5]==(0x600003,0,level,WIDTHS[level],HEIGHTS[level]),'layer ABI mismatch')
            require(desc[:6]==(0x600002,0,level,num,num,offset),'descriptor ABI mismatch')
            require(layer[11]>0 and desc[10]>0,'missing PL cycle counters')
        for index in range(offset,offset+num):
            x,y,score,octave,bin_id,m10,m01,angle=struct.unpack_from('<5I2iI',records,index*64)
            require(octave==level and 0<=x<WIDTHS[level] and 0<=y<HEIGHTS[level], 'PL coordinate/level mismatch')
            require(0<score<=255 and bin_id<32 and angle==bin_id*737280,'PL orientation/score mismatch')
    return dict(frame_id=fid,timestamp_ns=ts,role=role,count=count,counts=list(counts),offsets=list(offsets),
                engine_ns=struct.unpack_from('<Q',payload,64)[0],input_copy_ns=struct.unpack_from('<Q',payload,72)[0],
                simulated=bool(flags),records=records,stats=stats)


class Client:
    def __init__(self,host,port=5600,timeout=10,allow_simulated=False):
        self.sock=socket.create_connection((host,port),timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.allow_simulated=allow_simulated

    def close(self):
        self.sock.close()

    def extract(self,pixels,frame_id,timestamp_ns,role=0):
        start=time.monotonic_ns()
        self.sock.sendall(request_header(frame_id,timestamp_ns,role,pixels)+pixels)
        header=receive(self.sock,64)
        length=HEADER.unpack(header)[-4]
        require(length<=65152,'oversize ORB60 reply')
        payload=receive(self.sock,length)
        result=decode(header,payload,frame_id,timestamp_ns,role,self.allow_simulated)
        result['roundtrip_ns']=time.monotonic_ns()-start
        return result,payload


def b1_packet(result):
    """Map integer layer-center coordinates to original-image float coordinates.

    Preserve record order, binned R11 angle and descriptor bits. B1 has float
    keypoints, class_id=-1 and patch size31*scale, as ORBextractor expects.
    This is an ABI adapter, not a claim of equivalence to CPU ORB selection.
    """
    header=bytearray(64)
    struct.pack_into('<8sHHHBBQ8I',header,0,b'ORBFEAT\0',1,64,64,result['role'],0,
                     result['timestamp_ns'],960,720,result['count'],8,
                     struct.unpack('<I',struct.pack('<f',1.2))[0],1000,32,0)
    struct.pack_into('<I',header,56,result['count'])  # all monocular features
    output=bytearray(header)
    for index in range(result['count']):
        record=result['records'][index*64:(index+1)*64]
        x,y,score,level,bin_id,m10,m01,angle=struct.unpack_from('<5I2iI',record)
        # Match ORBextractor's float32 progression and final float32 products.
        scale=struct.unpack('<f',struct.pack('<f',1.2))[0]
        factor=1.0
        for _ in range(level):
            factor=struct.unpack('<f',struct.pack('<f',factor*scale))[0]
        output.extend(struct.pack('<ffi3fii',x*factor,y*factor,level,angle/65536.0,31*factor,float(score),-1,0))
        output.extend(record[32:])
    return bytes(output)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--port',type=int,default=5600)
    parser.add_argument('--gray',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frame-id',type=int,default=1)
    parser.add_argument('--timestamp-ns',type=int,default=1)
    parser.add_argument('--role',type=int,choices=(0,1),default=0)
    parser.add_argument('--repeat',type=int,default=1)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    client=Client(args.host,args.port)
    try:
        for n in range(args.repeat):
            result,payload=client.extract(args.gray.read_bytes(),args.frame_id+n,args.timestamp_ns+n,args.role)
            prefix=args.output/f'frame_{args.frame_id+n}'
            prefix.with_suffix('.payload').write_bytes(payload)
            prefix.with_suffix('.orb').write_bytes(b1_packet(result))
            metadata={k:v for k,v in result.items() if k not in ('records','stats')}
            prefix.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
            print(json.dumps(metadata),flush=True)
    finally:
        client.close()


if __name__=='__main__':
    main()
