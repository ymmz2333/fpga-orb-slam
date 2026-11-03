import pytest
from orb60.kv260.ps.build_packed_arm_crc import protocol_transform,packed_transform


def test_protocol_extension_preserves_original_software_crc():
    source='#ifndef ORB60_PROTOCOL_H\n#define ORB60_PROTOCOL_H\nstatic inline uint32_t orb_crc32(const void *p, size_t n) {\n existing_math();\n}\n#endif\n'
    changed=protocol_transform(source)
    assert source.removesuffix('#endif\n').replace('orb_crc32(','orb_crc32_software(') in changed
    assert 'HWCAP_CRC32' in changed and 'orb_crc32_arm(p,n):orb_crc32_software(p,n)' in changed
    with pytest.raises(ValueError):protocol_transform(source+source)
    with pytest.raises(ValueError):protocol_transform(source.replace('orb_crc32(', 'upstream_changed('))


def test_packed_bound_hoist_preserves_luma_order_and_lut():
    source='for(size_t i=0;i<gray.total();++i)gray.data[i]=lut[packed.data[i*2+channel]];'
    changed=packed_transform(source)
    assert changed=='const size_t pixels=gray.total();for(size_t i=0;i<pixels;++i)gray.data[i]=lut[packed.data[i*2+channel]];'
    with pytest.raises(ValueError):packed_transform(source+source)
    with pytest.raises(ValueError):packed_transform('upstream loop changed')
