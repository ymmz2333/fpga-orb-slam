"""Build a volatile UVC add-on for the exact factory kernel, without rebuilding Linux.

The factory's genksyms/modpost run on the ARM board as userspace tools. They do
not load drivers. Three explicit phases preserve symbol CRC validation; never
force vermagic, ignore undefined symbols, or replace the SD kernel.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,re,shutil,subprocess,sys,tarfile
from resource_guard import require_local_memory,ResourceDeferred
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=Path('C:/baidunetdiskdownload/ACZ7015_最核心学习资料_按顺序/06_Linux_PetaLinux_驱动/07_Linux源码/ACZ7015出厂工程和Linux源码/ACZ7015_Linux_Factory_Source.tar.gz')
ARCHIVE_SHA='41e9c2edcf4844f625129437306dcda6f4f1abf279cb8a63d83234a3aee266b5'
CONFIG_SHA='cc474754e590bf4665cd8a09250d68abe41197a5f2f9a7c619bffa75a173884c'
SYMVERS_SHA='db214db6ccdc55f73731c2c5fddb3db1410b178535cd538cc8c0d8dcb486c137'
TOOLBIN=Path('C:/Xilinx/SDK/2018.3/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
PROFILE=Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/zynq-arm-linux-2018.3.cmd')
PREFIX='arm-linux-gnueabihf-'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def prepare(archive):
    if sha(archive)!=ARCHIVE_SHA:raise RuntimeError('Factory archive SHA mismatch')
    kernel=ROOT/'build/camera_kernel_4_14_factory';kernel.mkdir(parents=True,exist_ok=True)
    prefix='ACZ7015_Linux_Factory_Source/linux/kernel/'
    selected=('include/','arch/arm/include/','drivers/media/usb/uvc/','drivers/media/v4l2-core/','scripts/mod/','scripts/genksyms/')
    names={'Makefile','.config','Module.symvers','COPYING','scripts/Makefile.build','scripts/Makefile.lib','scripts/Makefile.modpost','scripts/module-common.lds','scripts/Kbuild.include','arch/arm/Makefile','arch/arm/kernel/module.lds','drivers/media/Kconfig','drivers/media/usb/Kconfig','drivers/media/common/videobuf2/Kconfig','drivers/media/usb/Makefile'}
    manifest={};seen={};collisions=[]
    with tarfile.open(archive,'r|gz') as tar:
        for m in tar:
            if not m.isfile() or not m.name.startswith(prefix):continue
            rel=m.name[len(prefix):]
            if rel not in names and not rel.startswith(selected):continue
            if '..' in Path(rel).parts:raise RuntimeError('Unsafe source archive path')
            key=rel.lower()
            if key in seen and seen[key]!=rel:collisions.append([seen[key],rel]);continue
            seen[key]=rel;dst=kernel/rel;dst.parent.mkdir(parents=True,exist_ok=True)
            data=tar.extractfile(m).read();h=hashlib.sha256(data).hexdigest();manifest[rel]=h
            if dst.exists() and sha(dst)!=h:
                if rel!='scripts/mod/elfconfig.h' or dst.read_text() != data.decode().replace('HOST_ELFCLASS ELFCLASS64','HOST_ELFCLASS ELFCLASS32'):
                    raise RuntimeError('Prepared factory input modified: '+rel)
            else:
                if not dst.exists():dst.write_bytes(data)
    if sha(kernel/'.config')!=CONFIG_SHA or sha(kernel/'Module.symvers')!=SYMVERS_SHA:raise RuntimeError('Prepared config/symbol versions mismatch')
    # Generated host-tool header: host is ARM32, matching the board userspace.
    elf=kernel/'scripts/mod/elfconfig.h';elf.write_text(elf.read_text().replace('HOST_ELFCLASS ELFCLASS64','HOST_ELFCLASS ELFCLASS32'))
    manifest['scripts/mod/elfconfig.h']=sha(elf)
    (kernel/'uvc_extraction_manifest.json').write_text(json.dumps(dict(archive_sha256=ARCHIVE_SHA,files=manifest,unused_case_collisions=collisions,generated_host_elf_class=32),indent=2)+'\n')
    return kernel,manifest,collisions
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=['objects','versions','final'],required=True);p.add_argument('--archive',type=Path,default=ARCHIVE);p.add_argument('--build',type=Path);p.add_argument('--results',type=Path);args=p.parse_args()
    if args.phase!='objects' and (not args.build or not args.results):p.error('Later phases need --build and --results')
    kernel,manifest,collisions=prepare(args.archive)
    signature=dict(source_sha256=manifest,recipe_sha256=sha(Path(__file__)),compiler_sha256=sha(TOOLBIN/(PREFIX+'gcc.exe')),profile_sha256=sha(PROFILE),archive_sha256=ARCHIVE_SHA)
    if args.build:
        out=args.build.resolve()
        if out.parent!=(ROOT/'build').resolve() or not out.name.startswith('uvc_'):raise RuntimeError('Build must stay in this workspace build/uvc_*')
        report=json.loads((out/'checks.json').read_text())
        if report['signature']!=signature:raise RuntimeError('UVC source/toolchain/recipe changed; start a new build')
        if report['status']=='FAIL':raise RuntimeError('Inspect the failed UVC build; no automatic reuse')
        if report['status']=='DEFERRED_MEMORY' and report['phase']!=args.phase:raise RuntimeError('Resume the deferred phase before advancing')
        if args.phase=='objects' and report['status']!='DEFERRED_MEMORY':raise RuntimeError('Object phase can only resume a deferred build')
        for name,h in report.get('artifacts',{}).items():
            if sha(out/name)!=h:raise RuntimeError('UVC intermediate changed: '+name)
    else:
        out=ROOT/'build'/('uvc_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir()
        report=dict(signature=signature,status='RUNNING',phase=args.phase,commands=[],artifacts={},kernel_programmed=False,driver_loaded=False)
    env=os.environ.copy();system=Path(env.get('SystemRoot','C:/Windows'));env['PATH']=';'.join(map(str,[TOOLBIN,system/'System32',system]))
    def run(tool,words,name):
        words=list(map(str,words))
        if any('\n' in w or '\r' in w for w in words):raise RuntimeError('Invalid response argument')
        command=dict(tool=tool,args=words,name=name)
        existing=next((c for c in report['commands'] if c['name']==name),None)
        if existing:
            if existing['tool']!=tool or existing['args']!=words or existing['returncode']:raise RuntimeError('UVC resume command mismatch')
            return (out/(name+'.log')).read_text(errors='replace')
        require_local_memory('uvc '+name)
        rsp=out/(name+'.rsp');rsp.write_text('\n'.join('"'+w.replace('\\','\\\\').replace('"','\\"')+'"' for w in words)+'\n',encoding='ascii')
        launch=out/(name+'.cmd');launch.write_text('@echo off\ncall "'+str(PROFILE)+'" '+PREFIX+tool+' @"'+str(rsp)+'"\nexit /b %ERRORLEVEL%\n',encoding='ascii')
        log=out/(name+'.log')
        with log.open('w') as f:rc=subprocess.run([str(system/'System32/cmd.exe'),'/d','/c',launch.name],cwd=out,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
        command['returncode']=rc;report['commands'].append(command)
        if rc:print(log.read_text(errors='replace')[-10000:]);raise RuntimeError('UVC tool failed: '+name)
        if '-o' in words:
            artifact=Path(words[words.index('-o')+1]);report['artifacts'][artifact.relative_to(out).as_posix()]=sha(artifact)
        print('PASS',name,flush=True);return log.read_text(errors='replace')
    def bundle(name,files,script):
        stage=out/name;stage.mkdir(exist_ok=True)
        for path,relative in files:
            dst=stage/relative;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dst)
        (stage/'run.sh').write_text(script,encoding='ascii',newline='\n')
        (stage/'SHA256SUMS').write_text(''.join(sha(f)+'  '+f.relative_to(stage).as_posix()+'\n' for f in sorted(stage.rglob('*')) if f.is_file() and f.name!='SHA256SUMS'),encoding='ascii',newline='\n')
        with tarfile.open(out/(name+'.tar.gz'),'w:gz') as tar:tar.add(stage,arcname=name)
        report['artifacts'][name+'.tar.gz']=sha(out/(name+'.tar.gz'))
    base=['-D__KERNEL__','-DMODULE','-mlittle-endian','-nostdinc','-isystem',str(TOOLBIN.parent/'lib/gcc/arm-linux-gnueabihf/7.3.1/include')]
    for rel in ['arch/arm/include','arch/arm/include/generated','include','arch/arm/include/uapi','arch/arm/include/generated/uapi','include/uapi','include/generated/uapi']:base+=['-I'+str(kernel/rel)]
    base+=['-include',str(kernel/'include/linux/kconfig.h'),'-Wall','-Wundef','-Wstrict-prototypes','-Wno-trigraphs','-fno-strict-aliasing','-fno-common','-fshort-wchar','-Werror=implicit-function-declaration','-Wno-format-security','-std=gnu89','-fno-PIE','-fno-ipa-sra','-fno-dwarf2-cfi-asm','-mabi=aapcs-linux','-mno-thumb-interwork','-mfpu=vfp','-funwind-tables','-marm','-D__LINUX_ARM_ARCH__=7','-march=armv7-a','-msoft-float','-Uarm','-fno-delete-null-pointer-checks','-O2','-fno-stack-protector','-fomit-frame-pointer','-fno-strict-overflow','-fno-merge-all-constants','-fmerge-constants','-fconserve-stack','-Wframe-larger-than=2048','-Werror=date-time','-DCC_HAVE_ASM_GOTO','-DCONFIG_MEDIA_USB_SUPPORT=1','-DCONFIG_USB_VIDEO_CLASS_MODULE=1','-DCONFIG_VIDEOBUF2_VMALLOC_MODULE=1']
    if 'CONFIG_ARM_MODULE_PLTS=y' in (kernel/'.config').read_text():raise RuntimeError('This factory add-on flow requires the confirmed ARM_MODULE_PLTS disabled config')
    def flags(module,source):return base+['-DKBUILD_MODNAME="'+module+'"','-DKBUILD_BASENAME="'+source.replace('-','_')+'"']
    try:
        if args.phase=='objects':
            version=run('gcc',['--version'],'compiler_version')
            if '7.3.1' not in version or 'Linaro' not in version:raise RuntimeError('Requires SDK2018.3 GCC7.3.1')
            host=['-std=gnu99','-O2','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-static-libgcc']
            for name,folder,names in [('genksyms','scripts/genksyms',['genksyms.c','parse.tab.c','lex.lex.c']),('modpost','scripts/mod',['modpost.c','file2alias.c','sumversion.c'])]:
                objects=[]
                for source in names:
                    dst=out/(name+'_'+Path(source).stem+'.o');run('gcc',[*host,'-I'+str(kernel/folder),'-c',kernel/folder/source,'-o',dst],name+'_'+Path(source).stem);objects.append(dst)
                run('gcc',[*host,*objects,'-o',out/name],'link_'+name)
                elf=run('readelf',['-h','-A','-V',out/name],'elf_'+name)
                if 'ELF32' not in elf or 'ARM' not in elf:raise RuntimeError('Wrong ARM helper ABI')
            objects=[]
            for name in ['uvc_driver','uvc_queue','uvc_v4l2','uvc_video','uvc_ctrl','uvc_status','uvc_isight','uvc_debugfs','uvc_entity']:
                obj=out/(name+'.o');dep=out/(name+'.d');run('gcc',[*flags('uvcvideo',name),'-MMD','-MF',dep,'-c',kernel/'drivers/media/usb/uvc'/(name+'.c'),'-o',obj],name);objects.append(obj)
                deps=dep.read_text().replace('\\\n','').lower().replace('\\','/')
                for pair in collisions:
                    if any(item.lower() in deps for item in pair):raise RuntimeError('Case-colliding Linux header used; require case-sensitive build environment')
            run('ld',['-EL','-r',*objects,'-o',out/'uvcvideo.o'],'link_uvcvideo')
            for name in ['videobuf2-vmalloc','videobuf2-memops']:
                source=kernel/'drivers/media/v4l2-core'/(name+'.c')
                run('gcc',[*flags(name,name),'-E','-D__GENKSYMS__',source,'-o',out/(name+'.i')],'preprocess_'+name)
                if name=='videobuf2-vmalloc':run('gcc',[*flags(name,name),'-c',source,'-o',out/(name+'.tmp.o')],'compile_vmalloc')
            script='#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nsha256sum -c SHA256SUMS\nchmod 700 genksyms\n./genksyms -r /dev/null < videobuf2-memops.i > probe.lds\n./genksyms -r /dev/null < videobuf2-vmalloc.i > vmalloc.lds\nsha256sum probe.lds vmalloc.lds > result.sha256\ntar -czf genksyms-results.tar.gz probe.lds vmalloc.lds result.sha256\n'
            bundle('genksyms-stage',[(out/n,n) for n in ['genksyms','videobuf2-vmalloc.i','videobuf2-memops.i']],script)
            report.update(status='WAITING_ARM_GENKSYMS',phase='objects',next='Run genksyms-stage/run.sh on board (no module loading), retrieve genksyms-results.tar.gz and extract under workspace, then --phase versions --build THIS --results DIR')
        elif args.phase=='versions':
            if report['status'] not in ('WAITING_ARM_GENKSYMS','DEFERRED_MEMORY'):raise RuntimeError('Wrong UVC phase state')
            reference={line.split()[1]:int(line.split()[0],16) for line in (kernel/'Module.symvers').read_text().splitlines() if line.strip()}
            def crcs(path):return {name:int(value,16) for name,value in re.findall(r'__crc_(\w+)\s*=\s*(0x[0-9a-fA-F]+)',path.read_text())}
            probe=crcs(args.results/'probe.lds')
            if not probe or any(reference.get(name)!=value for name,value in probe.items()):raise RuntimeError('Known factory videobuf2 symbol CRC probe mismatch; do not build/load UVC')
            report['factory_crc_probe']=probe
            versions=crcs(args.results/'vmalloc.lds')
            if 'vb2_vmalloc_memops' not in versions:raise RuntimeError('VMALLOC symbol CRC missing')
            shutil.copy2(args.results/'vmalloc.lds',out/'vmalloc.lds')
            run('ld',['-EL','-r','-T',out/'vmalloc.lds',out/'videobuf2-vmalloc.tmp.o','-o',out/'videobuf2-vmalloc.o'],'version_vmalloc')
            script='#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nsha256sum -c SHA256SUMS\nchmod 700 modpost\n./modpost -m -i Module.symvers -o addon.symvers -S -E uvcvideo.o videobuf2-vmalloc.o\nsha256sum uvcvideo.mod.c videobuf2-vmalloc.mod.c addon.symvers > result.sha256\ntar -czf modpost-results.tar.gz uvcvideo.mod.c videobuf2-vmalloc.mod.c addon.symvers result.sha256\n'
            bundle('modpost-stage',[(out/n,n) for n in ['modpost','uvcvideo.o','videobuf2-vmalloc.o']]+[(kernel/'Module.symvers','Module.symvers')],script)
            report.update(status='WAITING_ARM_MODPOST',phase='versions',next='Run modpost-stage/run.sh on board (no module loading), retrieve/extract results, then --phase final --build THIS --results DIR')
        else:
            if report['status'] not in ('WAITING_ARM_MODPOST','DEFERRED_MEMORY'):raise RuntimeError('Wrong UVC phase state')
            for module in ['videobuf2-vmalloc','uvcvideo']:
                source=args.results/(module+'.mod.c')
                if 'module_layout' not in source.read_text():raise RuntimeError('Missing real MODVERSIONS metadata')
                dst=out/source.name;shutil.copy2(source,dst)
                run('gcc',[*flags(module,module+'_mod'),'-c',dst,'-o',out/(module+'.mod.o')],'metadata_'+module)
                run('ld',['-EL','-r','-T',kernel/'scripts/module-common.lds',out/(module+'.o'),out/(module+'.mod.o'),'-o',out/(module+'.ko')],'module_'+module)
                elf=run('readelf',['-h','-A','-S','-p','.modinfo',out/(module+'.ko')],'elf_module_'+module)
                for required in ['ELF32','ARM','4.14.0-xilinx','modversions','ARMv7','p2v8','__versions']:
                    if required not in elf:raise RuntimeError('Kernel module ABI/CRC section missing: '+required)
            report.update(status='PASS_BUILD_ONLY',phase='final',next='Inspect module metadata/import CRCs and matching live config before authorized volatile insmod; do not force module loading or modify SD')
    except ResourceDeferred as error:report.update(status='DEFERRED_MEMORY',phase=args.phase,error=str(error));print(error,flush=True);return 75
    except Exception as error:report.update(status='FAIL',phase=args.phase,error=str(error));raise
    finally:(out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],out,flush=True);return 0
if __name__=='__main__':raise SystemExit(main())
