"""Build and round-trip a metadata-only allocator xclbin; never loads it."""
import argparse,json,subprocess,hashlib
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--tool',type=Path,required=True)
    a=p.parse_args();folder=a.inputs.resolve();tool=a.tool.resolve();state=json.loads((folder/'METADATA_INPUTS.json').read_text())
    if state['platform_kind']!='dpu_points' or any(sha(folder/n)!=h for n,h in state['files'].items()):raise ValueError('Prepared point-platform metadata changed')
    if sha(tool)!='b09e16881b1c891abea0eab0deab529ddece216a7004ed0cff98155d73ec02d6':raise ValueError('Verified private official utility required')
    target=folder/'points_allocator.xclbin'
    if target.exists():raise ValueError('Fresh metadata build required')
    command=[str(tool),'--output',str(target)]
    names=['IP_LAYOUT','CONNECTIVITY','MEM_TOPOLOGY','CLOCK_FREQ_TOPOLOGY','EMBEDDED_METADATA']
    for n in names:
        xml=n=='EMBEDDED_METADATA';command+=['--add-section',n+(':'+ 'RAW:' if xml else ':JSON:')+str(folder/(n+('.xml' if xml else '.json')))]
    with (folder/'build.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
    dump=folder/'roundtrip';dump.mkdir()
    for n in names:
        if n in ('IP_LAYOUT','CONNECTIVITY'):continue # official utility omits zero-length arrays
        xml=n=='EMBEDDED_METADATA';dest=dump/(n+('.xml' if xml else '.json'))
        result=subprocess.run([str(tool),'--input',str(target),'--dump-section',n+(':RAW:' if xml else ':JSON:')+str(dest)],capture_output=True,text=True,timeout=30)
        (dump/(n+'.log')).write_text(result.stdout+result.stderr)
        result.check_returncode()
    ip=json.loads((folder/'IP_LAYOUT.json').read_text())['ip_layout'];mem=json.loads((dump/'MEM_TOPOLOGY.json').read_text())['mem_topology']
    con=json.loads((folder/'CONNECTIVITY.json').read_text())['connectivity']
    if int(ip['m_count']) or int(con['m_count']) or int(mem['m_count'])!=1:raise ValueError('Allocator must not schedule native DPU/UIO registers as XRT compute units')
    m=mem['m_mem_data'][0]
    if int(m['m_base_address'],0)!=0 or int(m['m_sizeKB'],0)!=0x200000 or m['m_tag']!='PS_DDR_HP2':raise ValueError('Shared DDR bounds mismatch')
    info=subprocess.run([str(tool),'--input',str(target),'--info'],capture_output=True,text=True,check=True,timeout=30)
    (folder/'info.log').write_text(info.stdout+info.stderr)
    if any(n in info.stdout for n in ('BITSTREAM','IP_LAYOUT','CONNECTIVITY')):raise ValueError('Metadata allocator must contain no bitstream or scheduled CU')
    report=dict(status='ALLOCATOR_METADATA_ROUNDTRIP_PASS',xclbin_sha256=sha(target),tool_sha256=sha(tool),
                platform_kind='dpu_points',release_manifest_sha256=state['release_manifest_sha256'],
                hardware_loaded=False,xrt_registered=False,scheduled_cus=0,bitstream_in_xclbin=False)
    (folder/'BUILD.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
