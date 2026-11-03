import hashlib
import socket
import struct
import threading
import zlib
import csv
import pytest
from orb60.kv260.localization_input import header,validate_ack,Sender,SIZE
from orb60.linux.client import receive


def ack(frame,stamp,crc):
    b=bytearray(b'ORBGRAY2'+struct.pack('<QQI',frame,stamp,crc)+bytes(4));struct.pack_into('<I',b,28,zlib.crc32(b[:28]));return bytes(b)


def test_header_is_explicit_fixed_gray_and_calibration_bound():
    digest=hashlib.sha256(b'calibration').hexdigest();h=bytearray(header(2,123,5,42,digest,0))
    assert len(h)==128 and h[:8]==b'ORBGRAY1' and h[64:]==digest.encode()
    assert struct.unpack_from('<IIQQ6I',h,8)==(1,128,2,123,SIZE,42,960,720,0,5)
    crc=struct.unpack_from('<I',h,56)[0];struct.pack_into('<I',h,56,0);assert zlib.crc32(h)==crc


@pytest.mark.parametrize('field,value',(('frame',-1),('stamp',0),('sequence',2**32),('mode',2),('calibration','x'*64)))
def test_invalid_wire_identity_rejected(field,value):
    a=dict(frame=0,stamp=1,sequence=0,crc=0,calibration='a'*64,mode=0);a[field]=value
    with pytest.raises(ValueError):header(**a)


@pytest.mark.parametrize('case',('exact','bad_crc','wrong_frame','short'))
def test_receipt_fragmentation_identity_and_latched_failure(case):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);errors=[]
    def peer():
        try:
            with listener.accept()[0] as s:
                h=receive(s,128);body=receive(s,SIZE);crc=zlib.crc32(body)
                assert struct.unpack_from('<I',h,36)[0]==crc
                b=bytearray(ack(0,100,crc))
                if case=='bad_crc':b[-1]^=1
                if case=='wrong_frame':b=bytearray(ack(1,100,crc))
                if case=='short':b=b[:9]
                s.sendall(b[:3]);s.sendall(b[3:])
        except BaseException as e:errors.append(e)
        finally:listener.close()
    thread=threading.Thread(target=peer);thread.start();sender=Sender('127.0.0.1',listener.getsockname()[1],b'camera',0)
    try:
        if case=='exact':assert sender.send(bytes(SIZE),0,100,50)==zlib.crc32(bytes(SIZE))
        else:
            with pytest.raises((ValueError,ConnectionError)):sender.send(bytes(SIZE),0,100,50)
            with pytest.raises(RuntimeError):sender.send(bytes(SIZE),1,101,51)
    finally:sender.close();thread.join(timeout=5)
    assert not thread.is_alive() and not errors


def test_paired_localization_rejects_missing_baseline_and_nonfinite_pose(tmp_path):
    from orb60.kv260.run_7015_network_localization import compare_recorded
    def write(folder,kind,row):
        folder.mkdir(exist_ok=True)
        with (folder/(kind+'.part000.csv')).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=row.keys());w.writeheader();w.writerow(row)
    actual,reference=tmp_path/'actual',tmp_path/'reference'
    pose=dict(frame_id='0',timestamp_ns='100',map_version='a'*64,pose_valid='1')
    pose.update({k:'0' for k in ('tx','ty','tz','r00','r01','r02','r10','r11','r12','r20','r21','r22')})
    timing=dict(features='700',pose_valid='1',matches='40',inliers='30')
    for folder in (actual,reference):write(folder,'poses',pose);write(folder,'timing',timing)
    assert compare_recorded(actual,reference)['max_abs_pose_difference']==0
    (reference/'timing.part000.csv').unlink()
    with pytest.raises(ValueError,match='Incomplete'):compare_recorded(actual,reference)
    write(reference,'timing',timing)
    pose['tx']='nan';write(actual,'poses',pose)
    with pytest.raises(ValueError,match='Non-finite'):compare_recorded(actual,reference)
