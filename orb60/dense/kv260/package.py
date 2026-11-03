"""Create a hashed source/replay handoff; never fabricate a missing DPU model."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile
from .common import digest,save


def package(root):
    root=Path(root).resolve();build=root/'orb60/build/kv260';target=build/'handoff';target.mkdir(exist_ok=True)
    sources=[]
    for folder in [root/'orb60/dense/kv260']:
        sources += [p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts]
    sources += [root/'orb60/dense'/f for f in ['__init__.py','geometry.py','video.py','ply.py']]
    for path in sources:
        dest=target/path.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    # Save all reports, but copy target xmodel only after actual compiler + placement acceptance.
    reports=[p for p in build.rglob('*') if p.is_file() and p.suffix in {'.json','.xml','.log','.txt','.png','.md'}
             and 'handoff' not in p.parts and 'replay_inputs' not in p.parts and 'reference_depth' not in p.parts
             and 'quantized_depth' not in p.parts and 'blocks' not in p.parts and p.stat().st_size<10_000_000]
    for path in reports:
        dest=target/'reports'/path.relative_to(build);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    accepted=False;compiled=build/'compiled/compilation.json'
    for name in ['arch.json','target_profile.json']:
        path=build/'compiled'/name
        if path.exists():
            (target/'models').mkdir(exist_ok=True);shutil.copyfile(path,target/'models'/name)
    if compiled.exists():
        r=json.loads(compiled.read_text());accepted=r.get('status')=='TARGET_COMPILE_PASS_BOARD_UNTESTED'
        if accepted:
            model=build/'compiled/midas_kv260_b4096.xmodel'
            if digest(model)!=r['model_sha256']:raise ValueError('Compiled model hash mismatch')
            (target/'models').mkdir(exist_ok=True)
            for name in ['midas_kv260_b4096.xmodel','arch.json','placement.json','target_profile.json','compilation.json']:
                shutil.copyfile(build/'compiled'/name,target/'models'/name)
    if not accepted and (target/'models/midas_kv260_b4096.xmodel').exists():raise ValueError('Stale model in handoff; choose clean output')
    diagnostic=build/'compiled_diagnostic';diagnostic_model=False
    if (diagnostic/'compilation.json').exists():
        info=json.loads((diagnostic/'compilation.json').read_text())
        if info.get('status')=='DIAGNOSTIC_ONLY_NOT_ACCEPTED':
            model=diagnostic/'midas_kv260_b4096.xmodel'
            if digest(model)!=info['model_sha256']:raise ValueError('Diagnostic model hash mismatch')
            (target/'diagnostic_models').mkdir(exist_ok=True)
            for name in ['midas_kv260_b4096.xmodel','arch.json','placement.json','target_profile.json','compilation.json']:
                shutil.copyfile(diagnostic/name,target/'diagnostic_models'/name)
            (target/'diagnostic_models/NOT_ACCEPTED.txt').write_text('Compiler succeeded, but the twenty-frame INT8 numerical gate FAILED. Not a deployable model.\n')
            if not accepted:
                for name in ['arch.json','target_profile.json']:shutil.copyfile(diagnostic/name,target/'models'/name)
            diagnostic_model=True
    # Twenty real inputs and original float predictions are the board numerical acceptance set.
    samples=root/'orb60/build/dense/samples-midas';reference=root/'orb60/build/dense/midas-small-fp16'
    (target/'acceptance/inputs').mkdir(parents=True,exist_ok=True);(target/'acceptance/reference').mkdir(exist_ok=True)
    shutil.copyfile(samples/'samples.json',target/'acceptance/inputs/samples.json')
    frames=json.loads((samples/'samples.json').read_text())['frames']
    (target/'acceptance/inputs/names.txt').write_text(''.join(f['id']+'\n' for f in frames))
    for f in frames:
        shutil.copyfile(samples/(f['id']+'.input.f32'),target/'acceptance/inputs'/(f['id']+'.input.f32'))
        shutil.copyfile(reference/(f['id']+'.reference.npy'),target/'acceptance/reference'/(f['id']+'.reference.npy'))
    fast=build/'fastdepth';fast_model=False
    if (fast/'compiled/compilation.json').exists():
        info=json.loads((fast/'compiled/compilation.json').read_text())
        if info.get('compiler_exit_code')==0 and info.get('model_sha256'):
            model=fast/'compiled'/info['model_file']
            if digest(model)!=info['model_sha256']:raise ValueError('FastDepth compiled model hash mismatch')
            dest=target/'diagnostic_models/fastdepth';dest.mkdir(parents=True,exist_ok=True)
            for name in [info['model_file'],'arch.json','placement.json','target_profile.json','compilation.json']:shutil.copyfile(fast/'compiled'/name,dest/name)
            (dest/'NOT_ACCEPTED.txt').write_text('DPU compilation passed. INT8 numerical acceptance FAILED. Experimental candidate only.\n')
            shutil.copytree(fast/'assets',target/'fastdepth_assets',dirs_exist_ok=True)
            for kind in ['inputs','reference']:(target/'acceptance_fastdepth'/kind).mkdir(parents=True,exist_ok=True)
            shutil.copyfile(samples/'samples.json',target/'acceptance_fastdepth/inputs/samples.json')
            (target/'acceptance_fastdepth/inputs/names.txt').write_text(''.join(f['id']+'\n' for f in frames))
            for f in frames:
                shutil.copyfile(samples/(f['id']+'.input.f32'),target/'acceptance_fastdepth/inputs'/(f['id']+'.input.f32'))
                shutil.copyfile(fast/'reference'/(f['id']+'.reference.npy'),target/'acceptance_fastdepth/reference'/(f['id']+'.reference.npy'))
            for name in ['cloud_reference','cloud_quantized']:shutil.copytree(fast/name,target/'candidate_fastdepth'/name,dirs_exist_ok=True)
            for name in ['pointcloud_preview.png','pointcloud_quantized_preview.png']:
                if (fast/name).exists():shutil.copyfile(fast/name,target/name)
            fast_model=True
    # Portable replay inputs include saved RGB, camera, observations, poses and their input tensors.
    replay=build/'replay_inputs';shutil.copytree(replay,target/'replay_inputs',dirs_exist_ok=True)
    cloud=build/'cloud_reference';shutil.copytree(cloud,target/'cloud_reference',dirs_exist_ok=True)
    if not fast_model and (build/'pointcloud_preview.png').exists():shutil.copyfile(build/'pointcloud_preview.png',target/'pointcloud_preview.png')
    status={'component_dpu_model_available':accepted,'diagnostic_model_available':diagnostic_model,'board_verified':False,
            'experimental_candidate':'fastdepth' if fast_model else 'midas','fastdepth_diagnostic_model_available':fast_model,
            'host_replay':json.loads((cloud/'result.json').read_text()),
            'pending':['Resolve INT8 numerical acceptance without weakening thresholds','KV260 read-only preflight','Real VART execution and 20-frame numerical gate','Board bandwidth/cache/video/power/temperature',
                       'Next round: unified ORB + DPU hardware platform and PS SLAM migration']}
    save(target/'HANDOFF_STATUS.json',status)
    (target/'README_FIRST.txt').write_text('Read orb60/dense/kv260/README.md and HANDOFF_STATUS.json first.\n'
        'FastDepth is the current experimental candidate: diagnostic_models/fastdepth and candidate_fastdepth. INT8 numerical acceptance has NOT passed.\n'
        'This package does not install firmware, change boot files, or prove hardware execution.\n'
        'A missing models/*.xmodel means target compilation has not passed; do not substitute a renamed file.\n'
        'Run from the extracted package root using python3 -m orb60.dense.kv260.<module>.\n')
    files={str(p.relative_to(target)).replace('\\','/'):digest(p) for p in sorted(target.rglob('*'))
           if p.is_file() and p.name!='SHA256SUMS.json'}
    save(target/'SHA256SUMS.json',files)
    archive=build/'kv260_dense_stage1_handoff.zip'
    with zipfile.ZipFile(archive.with_suffix('.part'),mode='w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for path in sorted(target.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(target))
    archive.with_suffix('.part').replace(archive)
    save(build/'package.json',{'file':archive.name,'sha256':digest(archive),'bytes':archive.stat().st_size,'files':len(files),**status})
    return archive


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(package(a.root))

if __name__=='__main__':main()
