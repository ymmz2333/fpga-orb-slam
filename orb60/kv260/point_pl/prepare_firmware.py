"""Prepare matched volatile-load assets; never loads hardware or edits Linux."""
import argparse,hashlib,json,shutil
from pathlib import Path
from orb60.kv260.pl.check_dpu_only import bit_fields


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(job,output):
    job,output=Path(job).resolve(),Path(output).resolve()
    m=json.loads((job/'release_manifest.json').read_text(encoding='utf-8'))
    if m.get('platform_kind')!='dpu_points' or not m.get('export_verified') or m['status']!='FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED':raise ValueError('Matched DPU+points export required')
    if any(sha(job/n)!=h for n,h in m['sha256'].items()):raise ValueError('Release file changed')
    if m['dpu_fingerprint']!='0x101000016010407' or m['clocks_mhz']!=dict(control_mhz=150,dpu_mhz=250,dsp_mhz=500):raise ValueError('Unreviewed DPU target or clocks')
    addresses={x.split('\t')[0]:tuple(int(v,0) for v in x.split('\t')[1:]) for x in (job/'address_map.tsv').read_text().splitlines()}
    required={'/ps/Data/SEG_dpu_reg0':(0xa1000000,0x1000000),'/ps/Data/SEG_point_project_Reg':(0xa2000000,0x10000)}
    for name in ('input','output'):required['/point_project/Data_m_axi_'+name+'_mem/SEG_ps_HP2_DDR_LOW']=(0,0x80000000)
    for master,port in [('INSTR','HPC0'),('DATA0','HP0'),('DATA1','HP1')]:required['/dpu/DPU0_M_AXI_'+master+'/SEG_ps_'+port+'_DDR_LOW']=(0,0x80000000)
    if any(addresses.get(k)!=v for k,v in required.items()):raise ValueError('Matched PS/PL address map required')
    source=Path(__file__).resolve().parents[1]/'pl/dpu_vivado_full_overlay.dts';text=source.read_text()
    firmware='kv260_dpu_points.bit.bin'
    if text.count('kv260-dpu-only.bit.bin')!=1 or not text.endswith('};\n'):raise ValueError('Unreviewed retained DPU overlay')
    text=text.replace('kv260-dpu-only.bit.bin',firmware)
    node='''    // The explicitly selected native DPU driver allocates shared DDR.
    // Do not create a second DRM/XRT device on this native Vivado platform.
    point_project_uio: point-project@a2000000 {
        compatible = "generic-uio";
        linux,uio-name = "kv260_point_project";
        reg = <0 0xa2000000 0 0x10000>;
        status = "okay";
    };
'''
    text=text[:-3]+node+'};\n'
    output.mkdir(parents=True,exist_ok=False)
    names=['kv260_dpu_points.bit','point_abi.json','release_manifest.json','address_map.tsv','methodology_review.json']
    for name in names:shutil.copyfile(job/name,output/name)
    (output/'firmware.bif').write_text('all:\n{\n  [destination_device=pl] kv260_dpu_points.bit\n}\n',encoding='utf-8')
    (output/'kv260_dpu_points.dts').write_text(text,encoding='utf-8')
    state=dict(status='FIRMWARE_INPUTS_PREPARED_BOARD_UNTESTED',hardware_loaded=False,platform_kind='dpu_points',release_sha256=sha(job/'release_manifest.json'),
               dpu_fingerprint=m['dpu_fingerprint'],bitstream_sha256=sha(job/'kv260_dpu_points.bit'),firmware_name=firmware,
               scope='Firmware/DT only; XRT metadata registration, real loading and fresh DPU+point preflight remain required. No persistent boot changes.',
               retained_warnings='Methodology TIMING-54 x2; CDC48Critical/62Warning; see copied methodology_review.json',
               inputs_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()})
    (output/'PREPARATION.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8');return state


def finalize(output):
    output=Path(output).resolve();state=json.loads((output/'PREPARATION.json').read_text(encoding='utf-8'))
    if state['status']!='FIRMWARE_INPUTS_PREPARED_BOARD_UNTESTED' or any(sha(output/n)!=h for n,h in state['inputs_sha256'].items()):raise ValueError('Prepared inputs changed')
    processed=(output/state['firmware_name']).read_bytes();payload=bit_fields((output/'kv260_dpu_points.bit').read_bytes())['e']
    if len(payload)%4 or processed!=b''.join(payload[i:i+4][::-1] for i in range(0,len(payload),4)):raise ValueError('bootgen firmware differs from word-swapped exact configuration payload')
    dt=(output/'overlay_roundtrip.dts').read_text()
    if 'kv260_point_project' not in dt or state['firmware_name'] not in dt or not all(x in dt.lower() for x in ('a1000000','a2000000')):raise ValueError('Compiled device tree lost required nodes')
    state.update(status='MATCHED_FIRMWARE_DT_PREPARED_BOARD_UNTESTED',files_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file() and p.name!='PREPARATION.json'})
    (output/'PREPARATION.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8');return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--finalize',action='store_true');a=p.parse_args()
    r=finalize(a.output) if a.finalize else prepare(a.job,a.output);print(json.dumps({k:r[k] for k in ('status','hardware_loaded','bitstream_sha256')}))
