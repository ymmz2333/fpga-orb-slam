import struct
import pytest
from orb60.kv260.point_pl.prepare_tagged import writes,TAG
from orb60.kv260.point_pl.config_identity import parse,validate

def pack(*words):return struct.pack('>'+str(len(words))+'I',*words)

def test_configuration_tag_is_not_found_inside_frame_data():
    # FDRI type2 payload deliberately contains a fake AXSS write packet.
    data=bytes.fromhex('ffffffffaa995566')+pack(0x30004000,0x50000003,0x3001a001,TAG,0xdeadbeef,0x3001a001,TAG,0x20000000)
    assert writes(data,13)==[TAG]

def test_missing_repeated_and_wrong_tags_remain_visible():
    sync=bytes.fromhex('aa995566')
    assert writes(sync+pack(0x20000000),13)==[]
    assert writes(sync+pack(0x3001a001,TAG,0x3001a001,TAG+1),13)==[TAG,TAG+1]

@pytest.mark.parametrize('data',[b'',bytes.fromhex('aa995566')+b'\x30',bytes.fromhex('aa995566')+pack(0x3001a002,TAG)])
def test_truncated_packet_cannot_validate_identity(data):
    with pytest.raises(ValueError):writes(data,13)

def test_real_configuration_parser_and_wrong_image():
    r=parse('zynqMP FPGA Configuration register contents are\nIDCODE -->\t4a49093\r\nAXSS -->\t4f525050\r\nSTAT -->\t16907ffc\r\n')
    validate(r,TAG)
    with pytest.raises(ValueError):validate(dict(r,AXSS=0),TAG)
    with pytest.raises(ValueError):validate(dict(r,IDCODE=0),TAG)
    with pytest.raises(ValueError):parse('AXSS --> 4f525050\nSTAT --> 16907ffc')
    with pytest.raises(ValueError):parse('AXSS --> 0\nAXSS --> 4f525050\nSTAT --> 0\nIDCODE --> 4a49093')
