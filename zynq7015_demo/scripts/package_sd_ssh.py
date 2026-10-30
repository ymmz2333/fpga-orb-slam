"""Assemble checked PS executables and ORB PL exports for SD-boot/SSH bring-up."""
from pathlib import Path
import argparse
import datetime
import json
import shutil
import struct
import subprocess
import sys
import tarfile
from synth_pl_2018 import digest, write_json, PROFILE

ROOT = Path(__file__).resolve().parents[1]


def bit_payload(path):
    data = path.read_bytes()
    pos = 2+struct.unpack_from('>H',data)[0]
    if struct.unpack_from('>H',data,pos)[0]!=1:
        raise ValueError('Unexpected bitstream header')
    pos += 2
    fields = {}
    for expected in b'abcde':
        tag = data[pos];pos += 1
        if tag!=expected:
            raise ValueError('Unexpected bitstream field')
        fmt = '>I' if tag==ord('e') else '>H'
        n = struct.unpack_from(fmt,data,pos)[0];pos += struct.calcsize(fmt)
        fields[chr(tag)] = data[pos:pos+n];pos += n
    if pos!=len(data) or len(fields['e'])%4 or not fields['b'].startswith(b'7z015clg485'):
        raise ValueError('Unexpected bitstream part/length')
    return fields['e']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bit',required=True,type=Path)
    parser.add_argument('--arm',required=True,type=Path)
    a = parser.parse_args()
    bit,arm = a.bit.resolve(),a.arm.resolve()
    hw = json.loads((bit/'status.json').read_text())
    sw = json.loads((arm/'checks.json').read_text())
    native = json.loads((ROOT/'build/native/checks.json').read_text())
    if any(r['status']!='PASS' for r in [hw,sw,native]):
        raise ValueError('Requires passed bit export, ARM build and native checks')
    for name,meta in hw['artifacts'].items():
        if digest(bit/name)!=meta['sha256']:
            raise ValueError('Export changed: '+name)
    for name,meta in sw['binaries'].items():
        if digest(arm/name)!=meta['sha256']:
            raise ValueError('ARM binary changed: '+name)
    for name,expected in sw['input_sha256'].items():
        if digest(ROOT/name)!=expected:
            raise ValueError('ARM source changed since build: '+name)
    out = ROOT/'output'/('sd_ssh_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    for folder in ['bin','firmware','hardware','scripts','config','evidence','kernel']:
        (out/folder).mkdir()
    (out/'licenses').mkdir()
    shutil.copyfile(ROOT/'vendor/opencv_p3p/LICENSE',out/'licenses/OpenCV-4.2.0-BSD.txt')
    shutil.copyfile(ROOT/'vendor/opencv_p3p/provenance.json',out/'licenses/p3p-provenance.json')
    for name in sw['binaries']:
        shutil.copyfile(arm/name,out/'bin'/name)
    shutil.copyfile(bit/'s_wrapper.bit',out/'firmware/s_wrapper.bit')
    for name in ['s_wrapper.hdf','s_wrapper.hwdef']:
        shutil.copyfile(bit/name,out/'hardware'/name)
    scripts=['board_inventory.sh','board_software_check.sh']
    if hw.get('video2'):scripts+=['load_hdmi_board.sh','bind_wc.sh','run_hdmi.sh','zslamctl.sh','zynq-slam.init','install_sd_boot.sh','restore_sd_boot.sh']
    for name in scripts:
        text = (ROOT/'scripts'/name).read_text().replace('\r\n','\n')
        (out/'scripts'/name).write_text(text,encoding='utf-8',newline='\n')
    for name in ['camera_example.csv','camera_handoff.csv']:
        shutil.copyfile(ROOT/'config'/name,out/'config'/name)
    shutil.copyfile(ROOT/'SD_SSH_ZH.md',out/'README_ZH.md')
    for source,target in [(bit/'status.json','bit_export.json'),(bit/'source_route_review.json','route_review.json'),
                          (arm/'checks.json','arm_build.json'),
                          (ROOT/'build/native/checks.json','native_checks.json')]:
        shutil.copyfile(source,out/'evidence'/target)
    firmware = out/'firmware'
    (firmware/'bitstream.bif').write_text('all:\n{\n    s_wrapper.bit\n}\n',encoding='ascii')
    launcher = firmware/'convert.cmd'
    launcher.write_text('@echo off\ncall "'+str(PROFILE)+'" bootgen -arch zynq -image bitstream.bif -process_bitstream bin\nexit /b %ERRORLEVEL%\n',encoding='ascii')
    with (firmware/'bootgen.log').open('w') as f:
        rc = subprocess.run([r'C:\Windows\System32\cmd.exe','/d','/c',launcher.name],
                            cwd=firmware,stdout=f,stderr=subprocess.STDOUT,timeout=120).returncode
    binary = firmware/'s_wrapper.bit.bin'
    if rc or not binary.is_file():
        raise RuntimeError('Bootgen conversion failed: '+str(firmware/'bootgen.log'))
    payload = bit_payload(firmware/'s_wrapper.bit')
    expected = b''.join(payload[i:i+4][::-1] for i in range(0,len(payload),4))
    # Installed Bootgen 2018.3 appends swapped 0x20000000 NOP words to
    # the next 32-byte boundary. Check every byte, including that padding.
    padding_words = ((-len(expected)) % 32)//4
    expected += bytes.fromhex('00000020')*padding_words
    if binary.read_bytes()!=expected:
        raise RuntimeError('Bootgen output differs from swapped payload plus checked NOP padding')
    if hw.get('video2'):
        handoff=ROOT.parent/'zynq7015_localization_handoff_20261022/zynq7015_localization_handoff_20261022'
        module=handoff/'reference/ps_writecombine/retained_build/orb60_wc_uio.ko'
        if digest(module)!='bdce5a843b2b63aa9fb4d8d01a3d10bdf0b4036c348543e3150c5cfe30af592f':
            raise ValueError('Paired kernel module changed')
        dt=ROOT/'output/dt_hdmi_20261023'
        if json.loads((dt/'semantic_check.json').read_text())['status']!='PASS':raise ValueError('DT semantic check failed')
        shutil.copyfile(module,out/'kernel/orb60_wc_uio.ko')
        shutil.copyfile(handoff/'reference/ps/retained_build/board-probe',out/'bin/board-probe')
        for name in ['system.dtb','orb60-hdmi.dtbo']:
            shutil.copyfile(dt/name,out/'hardware'/name)
        shutil.copyfile(dt/'semantic_check.json',out/'evidence/dt_semantic_check.json')
    manifest = dict(status='PACKAGE_VERIFIED',part=hw['part'],tool=hw['tool'],
                    arm_build=str(arm),bit_export=str(bit),
                    scope=hw.get('scope','ORB PL + PS SLAM/UI software'),video2=hw.get('video2',False),
                    boot_bin_generated=False,hardware_programmed=False,arm_board_execution='NOT_RUN',
                    firmware_conversion='Bootgen 2018.3; exact swapped payload + 32-byte NOP alignment PASS',
                    firmware_padding_nop_words=padding_words)
    write_json(out/'manifest.json',manifest)
    files = sorted(p for p in out.rglob('*') if p.is_file())
    (out/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.relative_to(out).as_posix()+'\n' for p in files),encoding='ascii',newline='\n')
    archive = out.with_suffix('.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(out,arcname=out.name)
    with tarfile.open(archive,'r:gz') as tar:
        for path in out.rglob('*'):
            if path.is_file():
                name=out.name+'/'+path.relative_to(out).as_posix()
                if tar.extractfile(name).read()!=path.read_bytes():
                    raise RuntimeError('Archive member mismatch: '+name)
    write_json(archive.with_suffix('.json'),dict(status='PASS',archive=str(archive),
               sha256=digest(archive),bytes=archive.stat().st_size,package=str(out)))
    print('PASS PACKAGE:',out,flush=True)
    print('ARCHIVE:',archive,flush=True)


if __name__=='__main__':
    main()
