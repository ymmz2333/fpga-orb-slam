"""One explicitly chosen deployment phase per invocation; no automatic retry."""
import argparse,hashlib,json,os,pwd,shutil,subprocess,time
from pathlib import Path
from .deploy_board import save,dpu_fingerprint

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('base','assets','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--stage',choices=['firmware','interfaces','driver'],required=True)
    p.add_argument('--module',type=Path);p.add_argument('--tagged-export',type=Path)
    p.add_argument('--load',action='store_true');a=p.parse_args()
    if not a.load or os.geteuid():raise ValueError('Explicit --load as root required')
    base=a.base.resolve();assets=a.assets.resolve();out=a.output.resolve();m=json.loads((assets/'PHASED.json').read_text())
    if m['status']!='PHASED_ASSETS_PREPARED_BOARD_UNTESTED' or any(sha(assets/n)!=h for n,h in m['files'].items()):raise ValueError('Phased assets changed')
    if sha(base/'PREPARATION.json')!=m['base_preparation_sha256'] or sha(base/m['firmware_name'])!=m['firmware_sha256']:raise ValueError('Matched firmware changed')
    if int(Path('/proc/sys/kernel/tainted').read_text())&128:raise RuntimeError('Clean boot required after a kernel Oops')
    overlays=Path('/sys/kernel/config/device-tree/overlays');starter=overlays/'k26-starter-kits_image_1'
    receipt=out/'deployment_receipt.json';boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if a.stage=='firmware':
        if not a.tagged_export:raise ValueError('Tagged configuration identity required; old overlay-only cold-load path is quarantined')
        tagged=json.loads(a.tagged_export.read_text())
        if tagged['status']!='TAGGED_SAME_ROUTE_EXPORT_PASS_BOARD_UNTESTED' or tagged['bitstream_sha256']!=m['bitstream_sha256'] or tagged['release_sha256']!=m['release_sha256']:
            raise ValueError('Matched independently verified tagged release required')
        if out.exists():raise ValueError('Fresh deployment output required')
        if {p.name for p in overlays.iterdir()}!={'k26-starter-kits_image_1'} or (starter/'path').read_text().strip()!='k26_starter_kits.dtbo':raise ValueError('Unexpected cold-boot overlay state')
        if Path('/sys/module/xlnx_dpu').exists():raise ValueError('Firmware phase requires no native DPU module')
        clk=Path('/sys/kernel/debug/clk/clk_summary').read_text();line=next((s.split() for s in clk.splitlines() if s.split() and s.split()[0]=='pl0_ref'),None)
        if not line or int(line[1])<1 or int(line[2])<1 or abs(int(line[4])-100000000)>10:raise ValueError('Expected enabled100MHz PL reference clock')
        out.mkdir();record=dict(status='PHASE_IN_PROGRESS',stage='firmware',boot_id=boot,platform_kind='dpu_points',
            bitstream_sha256=m['bitstream_sha256'],firmware_sha256=m['firmware_sha256'],release_sha256=m['release_sha256'],
            starter_overlay_retained=True,no_boot_files_changed=True,source_sha256=sha(Path(__file__)))
        record['expected_usr_access']=int(tagged['usr_access'],0)
    else:
        record=json.loads(receipt.read_text())
        expected='PHASED_FIRMWARE_PCAP_ID_PASS' if a.stage=='interfaces' else 'PHASED_INTERFACES_APPLIED'
        if record['status']!=expected or record['boot_id']!=boot or record['bitstream_sha256']!=m['bitstream_sha256']:raise ValueError('Previous phase or boot does not match')
        record.update(status='PHASE_IN_PROGRESS',stage=a.stage)
    save(receipt,record)
    try:
        if a.stage in ('firmware','interfaces'):
            if a.stage=='firmware':
                from .config_identity import read as read_identity,validate
                before,before_text=read_identity();(out/'pcap_before.txt').write_text(before_text)
                filename='kv260_points_%08x.bit.bin'%record['expected_usr_access']
                dest=Path('/lib/firmware')/filename
                if dest.exists() and sha(dest)!=m['firmware_sha256']:raise ValueError('Firmware collision')
                if not dest.exists():shutil.copyfile(base/m['firmware_name'],dest)
                manager=Path('/sys/class/fpga_manager/fpga0')
                record.update(stage='PROGRAMMING_FULL_FILE',manager_flags_before=(manager/'flags').read_text().strip(),pcap_before=before,firmware_filename=filename)
                save(receipt,record)
                # Cold boot leaves CONFIG_DMA_BUF (0x100) set on this Ubuntu.
                # Match official fpgautil's Full-file path: clear flags first.
                (manager/'flags').write_text('0')
                if int((manager/'flags').read_text(),16)!=0:raise RuntimeError('Full-file FPGA manager mode did not take effect')
                (manager/'firmware').write_text(filename)
                after,after_text=read_identity();(out/'pcap_after.txt').write_text(after_text)
                validate(after,record['expected_usr_access'])
                if (manager/'state').read_text().strip()!='operating':raise RuntimeError('Tagged FPGA did not reach operating state')
                record.update(status='PHASED_FIRMWARE_PCAP_ID_PASS',pcap_after=after,manager_flags_after=(manager/'flags').read_text().strip())
            else:
                if Path('/sys/module/xlnx_dpu').exists():raise ValueError('No DPU module before interface phase')
                subprocess.run(['modprobe','uio_pdrv_genirq'],check=True,timeout=10)
                from .config_identity import read as read_identity,validate
                validate(read_identity()[0],record['expected_usr_access'])
                target=overlays/'orb60_points_interfaces';target.mkdir()
                (target/'dtbo').write_bytes((assets/'interfaces.dtbo').read_bytes())
                if (target/'status').read_text().strip()!='applied':raise RuntimeError('Interface overlay not applied')
                record.update(status='PHASED_INTERFACES_APPLIED')
        else:
            from .config_identity import read as read_identity,validate
            validate(read_identity()[0],record['expected_usr_access'])
            if not a.module or sha(a.module)!='b3e40a05a349e692c410144c86b4c4ec29ae0c117a1be21fcce4837f08f13773':raise ValueError('Matched verified native module required')
            record['stage']='BINDING_MATCHED_NATIVE_MODULE';save(receipt,record)
            subprocess.run(['insmod',str(a.module.resolve())],check=True,timeout=15)
            if dpu_fingerprint()!=m['dpu_fingerprint']:raise RuntimeError('Actual DPU fingerprint mismatch')
            nodes=[p for p in Path('/sys/bus/platform/devices').iterdir() if p.name=='a2000000.point-project']
            if len(nodes)!=1:raise RuntimeError('Point platform device missing')
            node=nodes[0]
            if not (node/'driver').exists():
                (node/'driver_override').write_text('uio_pdrv_genirq\n');Path('/sys/bus/platform/drivers/uio_pdrv_genirq/bind').write_text(node.name)
            matches=[p for p in Path('/sys/class/uio').glob('uio*') if (p/'name').read_text().strip()=='kv260_point_project']
            if len(matches)!=1 or int((matches[0]/'maps/map0/addr').read_text(),0)!=0xa2000000:raise RuntimeError('Point UIO identity mismatch')
            uio=Path('/dev')/matches[0].name;owner=pwd.getpwnam('ubuntu')
            for device in (Path('/dev/dpu'),uio):os.chown(device,owner.pw_uid,owner.pw_gid);os.chmod(device,0o600)
            record.update(status='DPU_POINTS_LOADED',dpu_fingerprint=dpu_fingerprint(),point_uio=str(uio),point_uio_name='kv260_point_project',
                          memory_backend='native-dpu',scope='Actual matched phased load and identity; execution checked separately')
        record['completed_monotonic_ns']=time.monotonic_ns()
    except BaseException as e:record.update(status='PHASE_FAILED',error=repr(e));raise
    finally:save(receipt,record)
    print(json.dumps(record))

if __name__=='__main__':main()
