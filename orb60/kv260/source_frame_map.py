"""Bounded exact producer timestamp/index journal for the local GUI."""
from collections import deque
from pathlib import Path


class SourceFrameMap:
    def __init__(self,path):
        self.path=Path(path)
        self.file=self.path.open('x',encoding='ascii',newline='')
        self.file.write('timestamp_ns,source_frame_index\n');self.file.flush()
        self.recent=deque(maxlen=4096);self.rows=0;self.previous_stamp=-1;self.previous_frame=-1

    def append(self,stamp,frame):
        if stamp<=self.previous_stamp or frame<=self.previous_frame:raise ValueError('Nonmonotonic source identity')
        self.previous_stamp,self.previous_frame=stamp,frame
        row=f'{stamp},{frame}\n';self.file.write(row);self.file.flush();self.recent.append(row);self.rows+=1
        if self.rows>=8192:
            self.file.close();temporary=self.path.with_suffix('.part')
            temporary.write_text('timestamp_ns,source_frame_index\n'+''.join(self.recent),encoding='ascii')
            temporary.replace(self.path);self.file=self.path.open('a',encoding='ascii',newline='');self.rows=len(self.recent)

    def close(self):self.file.close()


class SourceFrameMapReader:
    """Consume each appended integer identity once; reset on atomic rotation."""
    def __init__(self,path):
        self.path=Path(path);self.identity=None;self.offset=0;self.pending=b''
        self.mapping={};self.header=False;self.last=(-1,-1);self.rows_parsed=0;self.bytes_read=0

    def update(self):
        with self.path.open('rb') as f:
            import os
            stat=os.fstat(f.fileno());identity=(stat.st_dev,stat.st_ino)
            if stat.st_size>1024*1024:raise ValueError('Local frame-map size exceeded')
            if identity!=self.identity or stat.st_size<self.offset:
                self.identity=identity;self.offset=0;self.pending=b''
                self.mapping.clear();self.header=False;self.last=(-1,-1)
            f.seek(self.offset);data=f.read(1024*1024+1)
        self.offset+=len(data);self.bytes_read+=len(data)
        data=self.pending+data;end=data.rfind(b'\n')+1
        complete,self.pending=data[:end],data[end:]
        for line in complete.splitlines():
            if not self.header:
                if line!=b'timestamp_ns,source_frame_index':raise ValueError('Local frame-map header mismatch')
                self.header=True;continue
            fields=line.split(b',')
            if len(fields)!=2 or not all(x.isdigit() for x in fields):raise ValueError('Invalid integer source identity')
            stamp,index=map(int,fields)
            if stamp<=self.last[0] or index<=self.last[1] or stamp<=0:raise ValueError('Nonmonotonic source identity')
            self.mapping[stamp]=index;self.last=(stamp,index);self.rows_parsed+=1
            if len(self.mapping)>8192:del self.mapping[next(iter(self.mapping))]
        return self.mapping


class FrozenFrameIdentities:
    def __init__(self,path,color_path=None):
        import csv
        path=Path(path)
        if path.stat().st_size>1024*1024:raise ValueError('Frozen identity file size exceeded')
        with path.open(newline='') as f:rows=list(csv.DictReader(f))
        self.expected={};previous=0
        if not 1<=len(rows)<=8192:raise ValueError('Frozen source row limit exceeded')
        for i,row in enumerate(rows):
            stamp,index,crc=map(int,(row['timestamp_ns'],row['source_frame_id'],row['gray_crc']))
            if stamp<=previous or index!=i or not 0<=crc<=0xffffffff:raise ValueError('Invalid frozen source identity')
            self.expected[stamp]=(index,crc);previous=stamp
        self.colors=None
        if color_path:
            color_path=Path(color_path)
            if color_path.stat().st_size>1024*1024:raise ValueError('Frozen RGB identity size exceeded')
            with color_path.open(newline='') as f:colors=list(csv.DictReader(f))
            if len(colors)!=len(rows):raise ValueError('Incomplete paired RGB identities')
            self.colors={}
            for i,(a,b) in enumerate(zip(rows,colors)):
                stamp,index,crc=map(int,(b['timestamp_ns'],b['source_frame_id'],b['bgr_crc']))
                if (stamp,index)!=(int(a['timestamp_ns']),i) or not 0<=crc<=0xffffffff:raise ValueError('Paired RGB identity mismatch')
                self.colors[stamp]=crc

    def check(self,meta):
        actual=(meta['frame_index'],meta['raw_gray_crc'])
        if self.expected.get(meta['timestamp_ns'])!=actual:raise ValueError('Preview source frame/timestamp/gray CRC differs from frozen input')
        if self.colors is not None and self.colors.get(meta['timestamp_ns'])!=meta.get('source_bgr_crc'):
            raise ValueError('Preview original RGB CRC differs from paired source')
