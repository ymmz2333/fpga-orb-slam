"""Snapshot a new DPU+point-project top from the verified DPU infrastructure."""
import argparse,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]

def replace(text,old,new,count=1):
    if text.count(old)!=count:raise ValueError('Infrastructure anchor changed: '+old[:100])
    return text.replace(old,new)

def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('hls',type=Path);p.add_argument('protocol',type=Path);p.add_argument('ooc',type=Path);a=p.parse_args()
    job=a.job.resolve();hls=a.hls.resolve();protocol=a.protocol.resolve();ooc=a.ooc.resolve()
    if not (hls/'unit_pass.stamp').exists():raise ValueError('HLS gates missing')
    proof=json.loads((protocol/'result.json').read_text());oc=json.loads((ooc/'ooc_pass.json').read_text())
    if proof['status']!='PASS' or not proof['reset_interruption'] or proof['transactions']!=9:raise ValueError('Protocol acceptance missing')
    if oc['status']!='OOC_PASS_NOT_SYSTEM' or min(oc['wns_ns'],oc['whs_ns'])<0:raise ValueError('OOC timing not closed')
    route=(ooc/'route_status.rpt').read_text()
    def nets(label):
        match=re.search(r'# of '+label+r'[. \t]*:\s*(\d+)',route)
        if not match:raise ValueError('OOC routing evidence missing: '+label)
        return int(match[1])
    if nets('routable nets')!=nets('fully routed nets') or nets('nets with routing errors')!=0:raise ValueError('OOC routing incomplete')
    if re.search(r'\|\s*(Error|Critical Warning)\s*\|',(ooc/'drc.rpt').read_text()):raise ValueError('OOC DRC failed')
    rtl=json.loads((protocol/'rtl_manifest.json').read_text())
    for name,expected in rtl.items():
        f=hls/'project/solution1/syn/verilog'/name
        if not f.exists():f=hls/'project/solution1/sim/verilog/ip/xil_defaultlib'/name
        if hashlib.sha256(f.read_bytes()).hexdigest()!=expected:raise ValueError('Protocol-tested RTL changed: '+name)
    job.mkdir(parents=True,exist_ok=False);source=job/'source_build';source.mkdir()
    base=ROOT/'orb60/kv260/pl';text=(base/'dpu_only.tcl').read_text()
    text=text.replace('kv260_dpu_only','kv260_dpu_points')
    text=replace(text,'set_property ip_repo_paths [list $repo]','set point_hls [file normalize $::env(POINT_HLS_JOB)]\n    set_property ip_repo_paths [list $repo [file join $point_hls project solution1 impl ip]]')
    text=replace(text,'CONFIG.PSU__USE__S_AXI_GP4 0','CONFIG.PSU__USE__S_AXI_GP4 1')
    text=replace(text,'# HP2/HP3 and all ORB logic are deliberately absent from this platform.','# HP2 carries the point-project kernel; HP3 remains disabled.')
    anchor='    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 control'
    point='''    create_bd_cell -type ip -vlnv xilinx.com:hls:point_project_hls:1.0 point_project
    wire clocks/clk_out1 point_project/ap_clk ps/saxihp2_fpd_aclk
    wire reset_control/peripheral_aresetn point_project/ap_rst_n
'''
    text=replace(text,anchor,point+anchor)
    text=text.replace('CONFIG.NUM_SI 1 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells control]', 'CONFIG.NUM_SI 1 CONFIG.NUM_MI 2 CONFIG.NUM_CLKS 1] [get_bd_cells control]')
    anchor='    axi control/M00_AXI dpu/S_AXI'
    text=replace(text,anchor,anchor+'''
    axi control/M01_AXI point_project/s_axi_control
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 point_mem
    set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells point_mem]
    wire clocks/clk_out1 point_mem/aclk
    wire reset_control/interconnect_aresetn point_mem/aresetn
    axi point_project/m_axi_input_mem point_mem/S00_AXI
    axi point_project/m_axi_output_mem point_mem/S01_AXI
    axi point_mem/M00_AXI ps/S_AXI_HP2_FPD''')
    text=replace(text,'CONFIG.CONST_WIDTH 7','CONFIG.CONST_WIDTH 6')
    text=replace(text,'CONFIG.NUM_PORTS 2 CONFIG.IN1_WIDTH 7','CONFIG.NUM_PORTS 3 CONFIG.IN1_WIDTH 1 CONFIG.IN2_WIDTH 6')
    text=replace(text,'wire irq_zero/dout interrupts/In1','wire point_project/interrupt interrupts/In1\n    wire irq_zero/dout interrupts/In2')
    text=replace(text,'    assign_bd_address\n','    assign_bd_address -offset 0xA2000000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs point_project/s_axi_control/Reg]\n    assign_bd_address\n')
    text=replace(text,'report_dpu_only.tcl','report_system.tcl')
    text=text.replace('Authored standalone K26 DPU platform. No ORB cores and no board programming.','Authored complete K26 DPU + point-project platform. No board programming.')
    (source/'system.tcl').write_text(text)
    report=(base/'report_dpu_only.tcl').read_text().replace('kv260_dpu_only','kv260_dpu_points')
    (source/'report_system.tcl').write_text(report)
    export=(base/'export_dpu_only.tcl').read_text().replace('kv260_dpu_only','kv260_dpu_points')
    (source/'export.tcl').write_text(export)
    check=(base/'check_dpu_only.py').read_text().replace('kv260_dpu_only','kv260_dpu_points').replace('"dpu_only"','"dpu_points"')
    check=replace(check,'complete KV260 standalone DPU routed top','complete KV260 DPU + point-project routed top')
    check=replace(check,'hls_count != 0','hls_count != 1')
    check=replace(check,'exactly one DPU and zero HLS IPs','exactly one DPU and one point-project HLS IP')
    check=replace(check,'    if (job / "build_config.json").exists():','''    if inventory_path.exists():
        if sum(v == "xilinx.com:hls:point_project_hls:1.0" for _, v in inventory) != 1:
            problems.append("Unexpected HLS kernel in complete top")
    if (job / "build_config.json").exists():''')
    (source/'check_system.py').write_text(check)
    for f in Path(__file__).parent.glob('*'):
        if f.is_file():(source/f.name).write_bytes(f.read_bytes())
    for name,folder in [('hls',hls),('protocol',protocol),('ooc',ooc)]:
        dst=job/'unit_evidence'/name;dst.mkdir(parents=True)
        names={'hls':['unit_pass.stamp','console.log'],'protocol':['result.json','rtl_manifest.json','abi.json'],'ooc':['ooc_pass.json','timing_summary.rpt','utilization.rpt']}[name]
        for f in names:(dst/f).write_bytes((folder/f).read_bytes())
    (job/'point_abi.json').write_bytes((protocol/'abi.json').read_bytes())
    ip=hls/'project/solution1/impl/ip'
    kernel_hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in ip.rglob('*') if f.is_file()}
    for f in (hls/'source').glob('*'):
        if f.is_file():kernel_hashes[str(f.relative_to(ROOT))]=hashlib.sha256(f.read_bytes()).hexdigest()
    (job/'kernel_provenance.json').write_text(json.dumps(kernel_hashes,indent=2)+'\n')
    check=(source/'check_system.py').read_text()
    anchor='    summary["status"] = '
    location=check.index(anchor)
    extra='''    provenance = job / "kernel_provenance.json"
    if not provenance.exists():
        problems.append("Kernel source/IP provenance missing")
    else:
        names += ["kernel_provenance.json", "point_abi.json", "source_manifest.json"]
        for relative, expected in json.loads(read(provenance)).items():
            file = ROOT / relative
            if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                problems.append("Tested HLS/IP changed: " + relative)
        for relative, expected in json.loads(read(job / "source_manifest.json")).items():
            if hashlib.sha256((job / relative).read_bytes()).hexdigest() != expected:
                problems.append("Top source snapshot changed: " + relative)
'''
    (source/'check_system.py').write_text(check[:location]+extra+check[location:])
    info=dict(platform_kind='dpu_points',control_mhz=150,dpu_mhz=250,dsp_mhz=500,board_verified=False,
              point_control_address=0xA2000000,point_hls=str(hls.relative_to(ROOT)),point_protocol=str(protocol.relative_to(ROOT)),point_ooc=str(ooc.relative_to(ROOT)))
    (job/'build_config.json').write_text(json.dumps(info,indent=2)+'\n')
    files={str(f.relative_to(job)):hashlib.sha256(f.read_bytes()).hexdigest() for f in source.iterdir() if f.is_file()}
    (job/'source_manifest.json').write_text(json.dumps(files,indent=2)+'\n')
    print('DPU_POINTS_SOURCE_READY',job)
if __name__=='__main__':main()
