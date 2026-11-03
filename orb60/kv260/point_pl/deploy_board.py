"""Explicit volatile board deployment. No boot files, package or governor edits."""
import argparse,array,fcntl,hashlib,json,os,pwd,shutil,time
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with p.open('w') as f:f.write(json.dumps(v,indent=2)+'\n');f.flush();os.fsync(f.fileno())

def dpu_fingerprint():
    fd=os.open('/dev/dpu',os.O_RDWR|os.O_CLOEXEC)
    try:
        fp=array.array('Q',[0]);fcntl.ioctl(fd,0x80084405,fp,True);return hex(fp[0])
    finally:os.close(fd)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--rollback',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--load',action='store_true');p.add_argument('--cold-boot',action='store_true');a=p.parse_args()
    if not a.load or os.geteuid()!=0:raise ValueError('Explicit --load as root required')
    assets=a.assets.resolve();old=a.rollback.resolve();out=a.output.resolve()
    if out.exists():raise ValueError('Fresh deployment receipt directory required')
    state=json.loads((assets/'PREPARATION.json').read_text());release=json.loads((assets/'release_manifest.json').read_text())
    if state['status']!='MATCHED_FIRMWARE_DT_PREPARED_BOARD_UNTESTED' or any(sha(assets/n)!=h for n,h in state['files_sha256'].items()):raise ValueError('Matched prepared assets changed')
    if state['release_sha256']!=sha(assets/'release_manifest.json') or state['platform_kind']!='dpu_points':raise ValueError('Wrong platform')
    for name in ('kv260-dpu-only.bit.bin','dpu-vivado-full.dtbo'):
        if not (old/name).is_file():raise ValueError('Retained native rollback assets required')
    users=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        for fd in (proc/'fd').glob('*'):
            try:target=os.readlink(fd)
            except OSError:continue
            if target=='/dev/dpu' or target.startswith('/dev/uio') or target.startswith('/dev/dri/render'):users.append((proc.name,target))
    if users:raise RuntimeError('Stop hardware users before reconfiguration: '+str(users))
    base=Path('/sys/kernel/config/device-tree/overlays');names={p.name for p in base.iterdir()}
    old_native=names=={'Full','orb60_dpu_vivado_driver'}
    # The first cold-load attempt lost SSH before completion. Its installed DT,
    # module binding order and persisted stage must be inspected before retry.
    if a.cold_boot:raise RuntimeError('Cold-boot deployment quarantined after transport loss; inspect carrier DT read-only first')
    if not old_native:raise ValueError('Unexpected overlay state: '+str(names))
    if old_native and (base/'Full/path').read_text().strip()!='kv260-dpu-only.dtbo':raise ValueError('Unexpected rollback origin')
    out.mkdir();report=dict(status='DEPLOYING',platform_kind='dpu_points',firmware_sha256=sha(assets/state['firmware_name']),
        overlay_sha256=sha(assets/'kv260_dpu_points.dtbo'),bitstream_sha256=state['bitstream_sha256'],
        release_manifest_sha256=sha(assets/'release_manifest.json'),no_boot_files_changed=True,
        before=dict(overlays=sorted(names),dpu_fingerprint=dpu_fingerprint() if Path('/dev/dpu').exists() else None),rollback=str(old))
    save(out/'deployment_receipt.json',report)
    firmware=Path('/lib/firmware')/state['firmware_name']
    if firmware.exists() and sha(firmware)!=report['firmware_sha256']:raise ValueError('Firmware filename collision')
    if not firmware.exists():shutil.copyfile(assets/state['firmware_name'],firmware)
    report['firmware_path']=str(firmware)
    target=base/'orb60_dpu_points'
    try:
        report['stage']='REMOVING_OWNED_OLD_OVERLAYS';save(out/'deployment_receipt.json',report)
        if old_native:(base/'orb60_dpu_vivado_driver').rmdir();(base/'Full').rmdir()
        report['stage']='LOADING_MATCHED_FIRMWARE_DT';save(out/'deployment_receipt.json',report)
        target.mkdir();(target/'dtbo').write_bytes((assets/'kv260_dpu_points.dtbo').read_bytes())
        report['stage']='CHECKING_ACTUAL_DEVICES';save(out/'deployment_receipt.json',report)
        deadline=time.monotonic()+15
        while not Path('/dev/dpu').exists() and time.monotonic()<deadline:time.sleep(.1)
        if (target/'status').read_text().strip()!='applied' or Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()!='operating':raise RuntimeError('FPGA/overlay did not reach operating/applied')
        fp=dpu_fingerprint()
        if fp!=release['dpu_fingerprint']:raise RuntimeError('Actual new DPU fingerprint mismatch')
        # A generic polled UIO device can be bound explicitly when the installed
        # module's OF match parameter is not configured. This changes this node only.
        nodes=[p for p in Path('/sys/bus/platform/devices').iterdir() if p.name.endswith('point-project') or p.name=='a2000000.point-project']
        if len(nodes)!=1:raise RuntimeError('Point platform node is missing or ambiguous: '+str(nodes))
        node=nodes[0]
        if not (node/'driver').exists():
            (node/'driver_override').write_text('uio_pdrv_genirq\n')
            Path('/sys/bus/platform/drivers/uio_pdrv_genirq/bind').write_text(node.name)
        deadline=time.monotonic()+5;matches=[]
        while not matches and time.monotonic()<deadline:
            matches=[p for p in Path('/sys/class/uio').glob('uio*') if (p/'name').read_text().strip()=='kv260_point_project'];time.sleep(.1)
        if len(matches)!=1 or int((matches[0]/'maps/map0/addr').read_text(),0)!=0xa2000000:raise RuntimeError('Point UIO identity/address mismatch')
        uio=Path('/dev')/matches[0].name;owner=pwd.getpwnam('ubuntu')
        for device in (uio,Path('/dev/dpu')):os.chown(device,owner.pw_uid,owner.pw_gid);os.chmod(device,0o600)
        os.chown(out,owner.pw_uid,owner.pw_gid)
        report.update(status='DPU_POINTS_LOADED',dpu_fingerprint=fp,point_uio=str(uio),point_uio_name='kv260_point_project',
                      fpga_state='operating',overlay_status='applied',scope='Actual volatile load and device identity only; point execution and VART inference remain separate checks')
    except BaseException as e:
        report.update(status='DEPLOYMENT_FAILED',error=repr(e));raise
    finally:save(out/'deployment_receipt.json',report)
    print(json.dumps(report))

if __name__=='__main__':main()
