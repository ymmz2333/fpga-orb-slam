"""Fail-closed complete DPU+points hardware handoff, without deployment."""
import argparse,hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);a=p.parse_args();job=a.job.resolve()
    env=dict(os.environ,FPGA_PROJECT_ROOT=str(ROOT))
    subprocess.run([sys.executable,str(job/'source_build/check_system.py'),str(job),'--release'],env=env,check=True,stdout=subprocess.DEVNULL)
    release=json.loads((job/'release_manifest.json').read_text());cfg=json.loads((job/'build_config.json').read_text())
    if not release.get('export_verified') or release['platform_kind']!='dpu_points':raise ValueError('Complete system acceptance missing')
    entries={'hardware/'+name:job/name for name in release['sha256']}
    for name in ['validation.json','release_manifest.json','project_path.txt','RESULT_ZH.md','MAIN_HANDOFF.md','methodology_review.json','system_generated.tcl']:
        entries[name]=job/name
    for base_name in ['source_build','unit_evidence']:
        for f in (job/base_name).rglob('*'):
            if f.is_file():entries[str(f.relative_to(job)).replace('\\','/')]=f
    for relative in json.loads((job/'kernel_provenance.json').read_text()):
        file=ROOT/relative
        if not file.resolve().is_relative_to(ROOT):raise ValueError('Kernel provenance escaped workspace')
        entries['workspace/'+relative.replace('\\','/')]=file
    for key in ['point_hls','point_protocol','point_ooc']:
        base=ROOT/cfg[key]
        for f in base.iterdir():
            if f.is_file() and f.suffix in ['.json','.log','.rpt','.tcl','.stamp']:entries['workspace/'+f.relative_to(ROOT).as_posix()]=f
    for folder in ['test_source','runtime']:
        for f in (ROOT/cfg['point_protocol']/folder).glob('*'):
            if f.is_file() and f.suffix in ['.py','.json']:entries['workspace/'+f.relative_to(ROOT).as_posix()]=f
    for f in (ROOT/cfg['point_hls']/'project/solution1/syn/report').glob('*.rpt'):entries['reports/'+f.name]=f
    for f in Path(__file__).parent.glob('*'):
        if f.is_file():entries['workspace/'+f.relative_to(ROOT).as_posix()]=f
    for name in ['project_env.ps1','local_env.example.ps1']:entries['workspace/scripts/'+name]=ROOT/'scripts'/name
    for name in ['dpu_only.tcl','report_dpu_only.tcl','export_dpu_only.tcl','check_dpu_only.py','prepare_unified_vendor.py']:
        entries['workspace/orb60/kv260/pl/'+name]=ROOT/'orb60/kv260/pl'/name
    for name in ['dense_fusion.py','runtime.py']:entries['workspace/orb60/kv260/'+name]=ROOT/'orb60/kv260'/name
    for name in ['geometry.py','ply.py']:entries['workspace/orb60/dense/'+name]=ROOT/'orb60/dense'/name
    model=ROOT/release['model_binding']['path'];entries['model/'+model.name]=model
    entries['provenance/DPU_PROVENANCE.json']=ROOT/'orb60/build/kv260_system/vendor_sources/DPU_PROVENANCE.json'
    files={name:dict(bytes=f.stat().st_size,sha256=digest(f)) for name,f in sorted(entries.items())}
    manifest=dict(status='FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED',platform_kind='dpu_points',files=files,
                  board_loaded=False,point_hardware_inference_verified=False,whole_system_speedup_verified=False)
    archive=job/'kv260_dpu_points_handoff.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as out:
        for name,f in entries.items():out.write(f,name)
        out.writestr('MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(archive) as check:
        if check.testzip():raise ValueError('Archive CRC failed')
        for name,record in files.items():
            if hashlib.sha256(check.read(name)).hexdigest()!=record['sha256']:raise ValueError('Archive hash mismatch: '+name)
    result=dict(status='HANDOFF_ARCHIVE_VERIFIED',archive=archive.name,bytes=archive.stat().st_size,
                sha256=digest(archive),files_verified=len(files),board_loaded=False)
    (job/'handoff_verified.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
