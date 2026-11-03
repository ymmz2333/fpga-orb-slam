"""PCAP configuration register identity, independent of PL AXI control ports."""
import re,subprocess
from pathlib import Path

def parse(text):
    result={}
    for name,value in re.findall(r'^\s*(\w+)\s*-->\s*([0-9a-fA-F]+)\s*$',text,re.MULTILINE):
        if name in result:raise ValueError('Repeated configuration register: '+name)
        result[name]=int(value,16)
    if not all(k in result for k in ('AXSS','IDCODE','STAT')):raise ValueError('PCAP configuration identity registers absent')
    return result

def read():
    mode=Path('/sys/module/zynqmp_fpga/parameters/readback_type').read_text().strip()
    if mode not in ('N','0'):raise ValueError('Configuration-register readback mode required; do not read frame data')
    r=subprocess.run(['cat','/sys/kernel/debug/fpga/fpga0/image'],capture_output=True,text=True,timeout=8)
    r.check_returncode();return parse(r.stdout),r.stdout

def validate(registers,tag):
    if registers['IDCODE']!=0x04a49093 or registers['AXSS']!=tag:raise ValueError('Actual FPGA configuration does not match the tagged K26 release')
