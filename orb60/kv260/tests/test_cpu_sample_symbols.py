import struct
import pytest
from orb60.kv260.ps.profile_native_cpu import elf_layout
from orb60.kv260.ps.analyze_native_cpu import Resolver,elf_address,parse_maps


def test_elf64_arm_load_segments_and_truncation(tmp_path):
    p=tmp_path/'a.so';ident=b'\x7fELF\x02\x01'+bytes(10)
    h=struct.pack('<16sHHIQQQIHHHHHH',ident,3,183,1,0,64,0,0,64,56,1,0,0,0)
    s=struct.pack('<IIQQQQQQ',1,5,0x1000,0x2000,0,0x300,0x300,4096)
    p.write_bytes(h+s);assert elf_layout(p)['segments'][0]['vaddr']==0x2000
    p.write_bytes(h+s[:-1])
    with pytest.raises(struct.error):elf_layout(p)


@pytest.mark.parametrize('kind,base,vaddr',[(3,0x900000,0x2000),(2,0x402000,0x402000)])
def test_pie_and_fixed_executable_offsets_are_not_confused(kind,base,vaddr):
    mapping=dict(start=base,end=base+0x1000,offset=0x1000,path='/project/lib.so')
    layout=dict(type=kind,segments=[dict(flags=5,offset=0x1000,vaddr=vaddr,filesz=0x300)])
    assert elf_address(base+0x30,mapping,layout)==vaddr+0x30
    with pytest.raises(ValueError):elf_address(base+0x400,mapping,layout)


def test_symbol_bounds_aliases_and_spaces():
    maps='900000-901000 r-xp 00001000 00:00 10 /project/lib with spaces.so\n'
    name='/project/lib with spaces.so'
    index={name:dict(layout=dict(type=3,segments=[dict(flags=5,offset=0x1000,vaddr=0x2000,filesz=0x300)]),symbol_files=['a.nm'])}
    text='00002020 00000020 W weak_alias()\n00002020 00000020 T actual_function(int)\n00002050 00000010 t next_function()\n'
    r=Resolver(maps,index,lambda p:text)
    assert r.resolve(0x900030)==(name,'actual_function(int)')
    assert r.resolve(0x900045)==(name,'[no function symbol]')
    assert r.resolve(0x900051)==(name,'next_function()')
    assert r.resolve(0x800000)==('[unmapped]','[unmapped]')
    assert parse_maps(maps)[0]['path']==name
