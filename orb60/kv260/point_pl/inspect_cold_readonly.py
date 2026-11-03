"""Recover cold-load state without probing any PL register or opening DPU/XRT."""
import argparse,hashlib,json,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh inspection output required')
    def read(path):
        try:return Path(path).read_text(errors='replace')
        except OSError as e:return repr(e)
    result=dict(scope='Read-only sysfs/proc/files; no PL register, DPU/XRT open, module, overlay, clock, reset or boot changes',
                uptime=read('/proc/uptime'),kernel_tainted=read('/proc/sys/kernel/tainted'),
                module_loaded=Path('/sys/module/xlnx_dpu').exists(),
                devices={str(p):p.exists() for p in map(Path,('/dev/dpu','/dev/uio4','/dev/dri/renderD128'))},
                overlays={p.name:{key:read(p/key) for key in ('status','path')} for p in Path('/sys/kernel/config/device-tree/overlays').iterdir()},
                dpu_dt_nodes=[dict(path=str(p.parent),compatible=p.read_bytes().decode(errors='replace'),status=read(p.parent/'status'))
                              for p in Path('/proc/device-tree').rglob('compatible') if b'dpuczdx' in p.read_bytes()],
                ip=subprocess.run(['ip','-br','addr'],capture_output=True,text=True).stdout,
                processes=subprocess.run(['ps','-eo','pid,stat,pcpu,comm,wchan:24'],capture_output=True,text=True).stdout,
                clock_summary=read('/sys/kernel/debug/clk/clk_summary'),
                kernel_log=subprocess.run(['dmesg'],capture_output=True,text=True).stdout,
                prior_receipts={})
    for p in (a.root/'platform_dpu_points').glob('deployment_*/deployment_receipt.json'):
        result['prior_receipts'][str(p)]=read(p)
    # Firmware-on-disk only. Never read the configfs binary dtbo attribute here.
    firmware=[]
    for base in (Path('/lib/firmware'),Path('/usr/lib/firmware')):
        for p in base.glob('**/k26_starter_kits.dtbo'):
            if p.is_file():firmware.append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    result['starter_firmware_files']=firmware
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('uptime','kernel_tainted','module_loaded','overlays','dpu_dt_nodes','prior_receipts')}))

if __name__=='__main__':main()
