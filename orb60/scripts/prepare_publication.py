"""Prepare a source/document publication; omit raw photos, credentials and builds."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SKIP_SUFFIX={'.pgm','.bin','.jpg','.png','.pyc','.exe','.dll'}
BRANCH='codex/orb60-100mhz-2ppc-pl-descriptor'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,text): path.write_text(text,encoding='utf-8',newline='')
def base_text(repo,name):
    return subprocess.check_output(['git','show','HEAD:'+name],cwd=repo).decode('utf-8')

def copy_tree(source,destination,omitted,record_cache=False):
    for p in sorted(source.rglob('*')):
        if not p.is_file(): continue
        relative=p.relative_to(source)
        if '__pycache__' in p.parts:
            if record_cache:omitted.append(dict(path=str(destination/relative),bytes=p.stat().st_size,sha256=sha(p),kind='frozen archival cache'))
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            omitted.append(dict(path=str(destination/relative),bytes=p.stat().st_size,sha256=sha(p)))
            continue
        out=destination/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out)

def prepare(root,repo):
    orb=root/'orb60';target=repo/'orb60'
    assert subprocess.check_output(['git','branch','--show-current'],cwd=repo,text=True).strip()==BRANCH
    assert subprocess.check_output(['git','diff','--cached','--name-only'],cwd=repo,text=True).strip()==''
    changed=set(subprocess.check_output(['git','diff','--name-only'],cwd=repo,text=True).splitlines())
    assert changed <= {'.gitignore','AGENTS.md','README.md'}, changed
    route=orb/'build/optimized/timing/20261012_134429_orb_100mhz_d4174613'
    layer=orb/'build/optimized/hls/20261012_112318_layer2_7d592c6c'
    descriptor=orb/'build/optimized/hls/20261012_132126_descriptor_9cae63b8'
    native=orb/'build/optimized/gates/20261012_155803_native_frame_d49eeb08'
    axi=orb/'build/optimized/gates/20261012_143039_datapath_axi_e0eb08c4'
    for job in (route,layer,descriptor,native,axi):
        assert json.loads((job/'status.json').read_text(encoding='utf-8-sig'))['State']=='SUCCEEDED'
    omitted=[]
    copy_tree(orb/'optimized',target/'optimized',omitted)
    copy_tree(orb/'scripts',target/'scripts',omitted)
    copy_tree(orb/'tests',target/'tests',omitted)
    copy_tree(orb/'vivado',target/'vivado',omitted)
    for name in ('AGENTS.md','WORKFLOW.md','provenance.json'):
        shutil.copyfile(orb/name,target/name)
    # Each frozen kernel preserves every compiled text input exactly, even when
    # unrelated source files changed between the two original synthesis jobs.
    for kernel,job in (('layer2',layer),('descriptor',descriptor)):
        frozen=target/'frozen/100mhz'/kernel
        copy_tree(job/'inputs',frozen/'inputs',omitted,record_cache=True)
        for name in ('source_manifest.json','status.json','hls.tcl'):
            shutil.copyfile(job/name,frozen/name)
        for name in (f'projects/{kernel}/solution1/syn/report/fastv2_{kernel}_hls_csynth.xml',
                     f'projects/{kernel}/solution1/syn/report/fastv2_{kernel}_hls_csynth.rpt',
                     f'projects/{kernel}/solution1/sim/report/fastv2_{kernel}_hls_cosim.rpt'):
            evidence=target/'evidence/100mhz/hls'/kernel;evidence.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(job/name,evidence/Path(name).name)
        driver=job/f'projects/{kernel}/solution1/impl/ip/drivers/fastv2_{kernel}_hls_v1_0/src/xfastv2_{kernel}_hls_hw.h'
        shutil.copyfile(driver,target/'evidence/100mhz/hls'/kernel/driver.name)
    evidence=target/'evidence/100mhz'
    copy_tree(route/'reports',evidence/'route',omitted)
    for folder,job,names in (
        ('route',route,('status.json',)),
        ('native',native,('status.json','performance.json','independent_result_audit.json','rtl_manifest.json','test_manifest.json','beats2_stall0.json','beats1_stall27.json')),
        ('axi',axi,('status.json',)),
        ('layer_acceptance',orb/'build/optimized/comparison/20261012_112245_layer2_6c71b587',('status.json','comparison.json')),
        ('descriptor_acceptance',orb/'build/optimized/comparison/20261012_134054_descriptor_recovery_cfb915fc',('status.json','comparison.json'))):
        out=evidence/folder;out.mkdir(parents=True,exist_ok=True)
        for name in names:shutil.copyfile(job/name,out/name)
    for kernel in ('layer2','descriptor'):
        out=evidence/'axi'/kernel;out.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(axi/kernel/'result.json',out/'result.json')
    for item in omitted: item['path']=Path(item['path']).relative_to(repo).as_posix()
    docs=target/'docs';docs.mkdir(parents=True,exist_ok=True)
    write(docs/'EXTERNAL_FIXTURES.json',json.dumps(omitted,indent=2)+'\n')
    write(target/'.gitignore','build/\nrelease/\n__pycache__/\n*.log\n')
    # No machine-specific user-profile paths enter new environment scripts.
    scripts=repo/'scripts';scripts.mkdir(exist_ok=True)
    env=(root/'scripts/project_env.ps1').read_text(encoding='utf-8-sig')
    begin=env.index("$BasePython = Get-FpgaSetting")
    end=env.index('\n\n',begin)
    env=env[:begin]+"$BasePython = [Environment]::GetEnvironmentVariable('FPGA_BASE_PYTHON','Process')"+env[end:]
    write(scripts/'project_env.ps1',env)
    write(scripts/'local_env.example.ps1',
        "# Copy to local_env.ps1 and override only installed tool paths.\n"
        "$env:FPGA_VIVADO_ROOT = 'D:\\Xilinx\\Vivado\\2024.2'\n"
        "$env:FPGA_VITIS_HLS_ROOT = 'D:\\Xilinx\\Vitis_HLS\\2024.2'\n"
        "# FPGA_BASE_PYTHON: installed CPython 3.12.12; create this checkout's .venv.\n")
    common=repo/'tb/common';common.mkdir(parents=True,exist_ok=True)
    for name in ('axi_lite.py','__init__.py'):shutil.copyfile(root/'tb/common'/name,common/name)
    ignore=repo/'.gitignore';write(ignore,base_text(repo,'.gitignore')+
        '\n# ORB60 branch source/build separation\n.venv/\n.work/\nscripts/local_env.ps1\n'
        '!orb60/artifacts/100mhz/*.bit\n!orb60/artifacts/100mhz/*.xsa\n')
    agents=repo/'AGENTS.md';write(agents,base_text(repo,'AGENTS.md')+
        '\n## ORB60 branch addition\n\n'
        'orb60/ is the independent 2024.2, xc7z015clg485-2, s_wrapper development\n'
        'scope. Its 100 MHz two-core hardware is separate from the historical\n'
        'R11 three-core bit/ELF. Use orb60/README_ZH.md and scripts/project_env.ps1.\n'
        'Frozen 100 MHz text inputs and evidence are immutable; modify authored\n'
        'optimized sources/generators. No new PS ELF or board result is claimed.\n')
    readme=repo/'README.md';write(readme,base_text(repo,'README.md')+
        '\n## 本分支新增：ORB60 100 MHz 开发版本\n\n'
        '新增共享读入的 2PPC 图像引擎和精确 A32 PL 描述子，使用 Vivado/Vitis HLS 2024.2。'
        '源码、冻结编译输入、完整路由和双核整帧仿真证据见 [ORB60 说明](orb60/README_ZH.md)。'
        '生成的 100 MHz bitstream 在 `orb60/artifacts/100mhz/`。'
        '当前 PS 固件未适配新控制接口；该开发 bitstream 不与历史 R11 ELF 配对。'
        '原有 R11 源码、默认固件说明及历史验收内容保留。\n')
    print(f'PUBLICATION_SOURCE_READY repo={repo} omitted_external_fixtures={len(omitted)}')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True)
    a=p.parse_args();prepare(a.root.resolve(),a.repo.resolve())
