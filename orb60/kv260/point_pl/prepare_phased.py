"""Derive separated firmware/interface overlays from matched prepared assets."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    base=a.base.resolve();out=a.output.resolve();m=json.loads((base/'PREPARATION.json').read_text())
    if m['status']!='MATCHED_FIRMWARE_DT_PREPARED_BOARD_UNTESTED' or any(sha(base/n)!=h for n,h in m['files_sha256'].items()):raise ValueError('Prepared matched assets changed')
    text=(base/'kv260_dpu_points.dts').read_text()
    if 'points-buffer-allocator' in text or text.count('&fpga_full')!=1 or text.count('&amba')!=1:raise ValueError('Explicit native-DPU allocator assets required')
    out.mkdir(parents=True,exist_ok=False)
    header='/dts-v1/;\n/plugin/;\n'
    sections={'firmware':text[text.index('&fpga_full'):text.index('&amba')], 'interfaces':text[text.index('&amba'):]}
    for name,body in sections.items():
        (out/(name+'.dts')).write_text(header+body,encoding='utf-8')
        prefix=['wsl.exe','--cd',str(out),'-e'] if os.name=='nt' else []
        for cmd in (['dtc','-@','-I','dts','-O','dtb','-o',name+'.dtbo',name+'.dts'],['dtc','-I','dtb','-O','dts','-o',name+'.roundtrip.dts',name+'.dtbo']):
            r=subprocess.run(prefix+cmd,cwd=out,capture_output=True,text=True);(out/(name+'.'+('compile' if '-@' in cmd else 'roundtrip')+'.log')).write_text(r.stdout+r.stderr)
            r.check_returncode()
    firmware=(out/'firmware.roundtrip.dts').read_text();interfaces=(out/'interfaces.roundtrip.dts').read_text()
    if any(x in firmware for x in ('a1000000','a2000000','compatible')) or m['firmware_name'] not in firmware:raise ValueError('Firmware phase unexpectedly adds MMIO devices')
    if 'firmware-name' in interfaces or not all(x in interfaces for x in ('a1000000','a2000000','kv260_point_project')):raise ValueError('Interface phase lost MMIO or reprograms FPGA')
    manifest=dict(status='PHASED_ASSETS_PREPARED_BOARD_UNTESTED',base_preparation_sha256=sha(base/'PREPARATION.json'),
        firmware_sha256=sha(base/m['firmware_name']),firmware_name=m['firmware_name'],bitstream_sha256=m['bitstream_sha256'],
        release_sha256=m['release_sha256'],dpu_fingerprint=m['dpu_fingerprint'],files={p.name:sha(p) for p in out.iterdir() if p.is_file()},
        sequence=['firmware only; no MMIO devices','interfaces only; no FPGA programming','verified native module bind, then actual device identity'])
    (out/'PHASED.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest))

if __name__=='__main__':main()
