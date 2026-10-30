"""Publish paired accepted4PPC sources/evidence without changing historical release."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def copy(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
def tree(source,destination):
    for path in source.rglob('*'):
        if path.is_file() and not any(n in ('__pycache__','.git','build') for n in path.relative_to(source).parts) and path.suffix not in ('.pyc','.exe','.obj','.log') and path.name!='local_env.ps1':
            copy(path,destination/path.relative_to(source))
def selected(source,destination,names):
    for name in names:
        path=source/name
        if path.is_file():copy(path,destination/name)

def run(a):
    root=a.root.resolve();repo=a.repo.resolve();job=a.job.resolve();output=a.output.resolve();orb=root/'orb60'
    assert repo.is_relative_to(root/'repos') and (repo/'.git').is_dir()
    branch=subprocess.check_output(['git','-C',str(repo),'branch','--show-current'],text=True).strip()
    assert branch=='codex/orb60-4ppc','Preserve main and historical release'
    assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip(),'Prepare on a clean publication checkout'
    state=read(job/'status.json');assert state['State']=='SUCCEEDED' and state['Stage']=='COMPUTER_GATES_COMPLETE'
    bit=read(job/'bit/status.json');assert bit['State']=='SUCCEEDED'
    pair=read(job/'bit/joint_validation.json');assert pair['engineering14ms_pass']
    route=Path(state['RouteJob']);frame=Path(state['FrameJob']);protocol=Path(read(frame/'status.json')['ProtocolJob']);unit=Path(state['MergeAxisJob'])
    origins={k:Path(read(route/'status.json')[key]) for k,key in [('layer2','LayerHlsJob'),('descriptor','DescriptorHlsJob')]}
    for origin in origins.values():
        for entry in read(origin/'source_manifest.json'):assert sha(origin/'inputs'/entry['Path']).upper()==entry['SHA256']
    # Prove the live shared source copy covers every local descriptor include.
    next_rel=Path('FPGA_ORB_HLS/fastv2/next');desc_base=origins['descriptor']/'inputs'/next_rel
    image_base=origins['layer2']/'inputs'/next_rel
    pending=[Path('src/descriptor_hls.cpp')];closure=set()
    while pending:
        rel=pending.pop()
        if rel in closure:continue
        closure.add(rel);assert sha(desc_base/rel)==sha(image_base/rel),f'Unpaired backend dependency: {rel}'
        for name in re.findall(r'#include\s+"([^"]+)"',(desc_base/rel).read_text()):
            found=[p for p in (rel.parent/name,Path('include')/name,Path('src')/name) if (desc_base/p).is_file()]
            assert found,f'Unresolved local backend include: {name}'
            pending.append(found[0])
    tree(origins['layer2']/'inputs/FPGA_ORB_HLS',repo/'orb60/optimized/FPGA_ORB_HLS')
    tree(origins['layer2']/'inputs/FPGA_ORB_SHARED_v1.0',repo/'orb60/optimized/FPGA_ORB_SHARED_v1.0')
    for folder in ('scripts','tests','vivado','docs'):
        tree(orb/folder,repo/'orb60'/folder)
    selected(orb,repo/'orb60',['AGENTS.md','WORKFLOW.md'])
    # Exact per-kernel snapshots, including vector provenance, are immutable.
    for kernel,origin in origins.items():
        dest=repo/'orb60/frozen/integrated4_100mhz'/kernel
        tree(origin/'inputs',dest/'inputs')
        # Preserve every frozen byte as provenance, including generator caches.
        # These historical caches are data only and are never executed.
        for entry in read(origin/'source_manifest.json'):
            copy(origin/'inputs'/entry['Path'],dest/'inputs'/entry['Path'])
        selected(origin,dest,['status.json','source_manifest.json','hls.tcl'])
    artifact=repo/'orb60/artifacts/integrated4_100mhz'
    selected(job/'bit',artifact,['orb60_100mhz.bit','status.json','joint_validation.json','bit_metrics.tsv','bit_check_timing.rpt','bit_route_status.rpt','bit_drc.rpt'])
    assert sha(artifact/'orb60_100mhz.bit')==bit['BitSha256'].lower()
    write(artifact/'artifact_manifest.json',dict(status='PASS',part='xc7z015clg485-2',frequency_mhz=100,layer_ppc=4,
        bit_sha256=bit['BitSha256'].lower(),checkpoint_sha256=pair['checkpoint_sha256'],joint_validation=pair,
        build_flags=dict(layer=dict(LayerPpc=4,FastStaged=True,LayerIoOverlap=True,LayerBramFifos=True),
                         descriptor=dict(DescriptorWidthMode=2,DescriptorPrefetch=8,DescriptorPatch32=True)),
        backend_source_closure=[p.as_posix() for p in sorted(closure)],ps_modified=False,physical_board_verified=False))
    evidence=repo/'orb60/evidence/integrated4_100mhz'
    tree(route/'reports',evidence/'route')
    selected(route,evidence/'route',['status.json','tool_manifest.json'])
    selected(route/'inputs',evidence/'route/inputs',['ip_manifest.json','timing_checks.tcl','build_orb_system.tcl'])
    selected(frame,evidence/'native',['status.json','performance.json','rtl_manifest.json','test_manifest.json','profile_manifest.json','delay_audit.json'])
    tree(frame/'inputs',evidence/'native/inputs')
    for path in frame.glob('beats*.json'):copy(path,evidence/'native'/path.name)
    selected(protocol,evidence/'protocol',['status.json','test_manifest.json'])
    tree(protocol/'inputs',evidence/'protocol/inputs')
    for kernel in origins:
        selected(protocol/kernel,evidence/'protocol'/kernel,['status.json','result.json','config.json','rtl_manifest.json','reuse.json'])
    selected(unit,evidence/'merge4',['status.json','result.json','test_manifest.json','rtl_manifest.json','source_pair.json'])
    for kernel,origin in origins.items():
        selected(origin,evidence/'hls'/kernel,['status.json','source_manifest.json'])
        accepted=job/('accepted_layer' if kernel=='layer2' else 'accepted_descriptor')
        copy(accepted/'comparison.json',evidence/'hls'/kernel/'comparison.json')
        tree(origin/f'projects/{kernel}/solution1/syn/report',evidence/'hls'/kernel/'reports')
        selected(origin/f'projects/{kernel}/solution1/sim/report',evidence/'hls'/kernel/'reports',[f'fastv2_{kernel}_hls_cosim.rpt'])
        driver=origin/f'projects/{kernel}/solution1/impl/ip/drivers/fastv2_{kernel}_hls_v1_0/src'
        for header in driver.glob('*_hw.h'):copy(header,evidence/'registers'/header.name)
    copy(job/'status.json',evidence/'integrated_status.json')
    for source,dest in [(job/'metrics_comparison',evidence/'comparison'),(job/'comparison_audit',evidence/'metric_audit')]:
        if source.is_dir():tree(source,dest)
    # These independent fixtures are small files; include them directly for reproducibility.
    fixture=repo/'orb60/fixtures/integrated4'
    benchmark=Path(state['BenchmarkJob'])
    tree(benchmark/'vectors',fixture/'benchmark/vectors');copy(benchmark/'status.json',fixture/'benchmark/origin_status.json')
    tree(origins['descriptor']/'descriptor_vectors',fixture/'descriptor_vectors')
    # Read-only verifier is independent of local absolute provenance paths.
    (repo/'tools/verify_integrated4.ps1').write_text('''[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$checkRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$checkManifest=Get-Content -LiteralPath (Join-Path $checkRoot 'orb60/INTEGRATED4_MANIFEST.json') -Raw | ConvertFrom-Json
foreach($entry in $checkManifest.files) {
    if((Get-FileHash -LiteralPath (Join-Path $checkRoot $entry.path)).Hash.ToLowerInvariant() -ne $entry.sha256) {throw "Publication mismatch: $($entry.path)"}
}
$checkArtifact=Get-Content -LiteralPath (Join-Path $checkRoot 'orb60/artifacts/integrated4_100mhz/artifact_manifest.json') -Raw | ConvertFrom-Json
if($checkArtifact.status -ne 'PASS' -or $checkArtifact.layer_ppc -ne 4 -or !$checkArtifact.joint_validation.engineering14ms_pass) {throw 'Missing accepted4PPC evidence'}
Write-Output "INTEGRATED4_PUBLICATION_PASS files=$($checkManifest.files.Count)"
Write-Output 'File integrity only; board/cache/videoP99 remains unverified.'
''',encoding='utf-8')
    output.mkdir(parents=True,exist_ok=True)
    write(output/'prepared.json',dict(status='PREPARED',repository=str(repo),integrated_job=str(job),bit_sha256=bit['BitSha256'].lower(),prepared_utc=datetime.now(timezone.utc).isoformat()))
    print('INTEGRATED4_PUBLICATION_PREPARED',repo)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','repo','job','output'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
