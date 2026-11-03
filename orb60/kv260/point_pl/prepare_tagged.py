"""Fresh derivative of the accepted route, with a PCAP-readable identity tag."""
import argparse,hashlib,json,shutil,struct
from pathlib import Path
from orb60.kv260.pl.check_dpu_only import bit_fields

TAG=0x4f525050
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def writes(payload,register):
    sync=payload.find(bytes.fromhex('aa995566'))
    if sync<0:raise ValueError('Missing FPGA sync word')
    pos=sync+4;reg=None;out=[]
    while pos<len(payload):
        if pos+4>len(payload):raise ValueError('Unaligned FPGA packet')
        header=struct.unpack_from('>I',payload,pos)[0];pos+=4;kind=header>>29;op=(header>>27)&3
        if kind==1:reg=(header>>13)&0x3fff;count=header&0x7ff
        elif kind==2:count=header&0x7ffffff
        elif header in (0,0xffffffff):continue
        else:raise ValueError('Unexpected FPGA packet type')
        end=pos+4*count
        if end>len(payload):raise ValueError('Truncated FPGA packet payload')
        if op==2 and reg==register:out.extend(struct.unpack_from('>'+str(count)+'I',payload,pos))
        pos=end
    return out

def prepare(parent,out):
    m=json.loads((parent/'release_manifest.json').read_text())
    if m['platform_kind']!='dpu_points' or not m['export_verified'] or m['status']!='FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED':raise ValueError('Accepted complete routed parent required')
    if any(sha(parent/n)!=h for n,h in m['sha256'].items()):raise ValueError('Retained parent changed')
    out.mkdir(parents=True,exist_ok=False)
    # Exact retained reports/checkpoint are inherited, never regenerated claims.
    for name in m['sha256']:shutil.copyfile(parent/name,out/name)
    for name in ['source_build','unit_evidence']:shutil.copytree(parent/name,out/name)
    for name in ['static_pass.stamp','methodology_review.json']:shutil.copyfile(parent/name,out/name)
    record=dict(status='TAGGED_EXPORT_PREPARED',parent=str(parent),parent_release_sha256=sha(parent/'release_manifest.json'),
                routed_dcp_sha256=m['sha256']['routed.dcp'],usr_access=hex(TAG),
                scope='Same routed fabric and retained STA; change only configuration USR_ACCESS, no new place/route or board acceptance')
    (out/'TAGGED_EXPORT.json').write_text(json.dumps(record,indent=2)+'\n');return record

def finalize(out):
    r=json.loads((out/'TAGGED_EXPORT.json').read_text());m=json.loads((out/'release_manifest.json').read_text())
    if m.get('export_verified') is not True or m['status']!='FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED':raise ValueError('Independent retained full-top/export checker failed')
    if sha(out/'routed.dcp')!=r['routed_dcp_sha256']:raise ValueError('Routed fabric checkpoint changed')
    values=writes(bit_fields((out/'kv260_dpu_points.bit').read_bytes())['e'],13)
    if values!=[TAG]:raise ValueError('Bitstream does not contain the exact single USR_ACCESS tag: '+str(values))
    r.update(status='TAGGED_SAME_ROUTE_EXPORT_PASS_BOARD_UNTESTED',bitstream_sha256=sha(out/'kv260_dpu_points.bit'),
             release_sha256=sha(out/'release_manifest.json'),usr_access_writes=values)
    (out/'TAGGED_EXPORT.json').write_text(json.dumps(r,indent=2)+'\n');return r

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--finalize',action='store_true');a=p.parse_args()
    print(json.dumps(finalize(a.output.resolve()) if a.finalize else prepare(a.parent.resolve(),a.output.resolve())))
