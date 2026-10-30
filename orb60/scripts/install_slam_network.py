"""Install the reproducible PC network adapter into the existing WSL checkout.

Run with WSL Python. Windows patches remain the source of truth. No RK3588 job
is started and no CPU baseline mode is changed.
"""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    root=a.source.resolve();workspace=a.workspace.resolve()
    patches=workspace/'rk3588/orbslam3_cpu_baseline/patches'
    frame=patches/'0018-fpga-frame-pipeline.patch'
    if frame.exists() and subprocess.run(['git','apply','--reverse','--check','-C0',str(frame)],cwd=root,capture_output=True).returncode==0:
        for name in ('FpgaORB.h','FpgaPipeline.h','FpgaReplayInput.h'):
            shutil.copyfile(patches/name,root/'include'/name)
        shutil.copyfile(workspace/'orb60/linux/protocol.h',root/'include/Orb60Protocol.h')
        print('SLAM_PIPELINE_PATCH_ALREADY_APPLIED');return
    patch=patches/'0016-zynq-network-orb.patch'
    if patch.exists():
        if subprocess.run(['git','apply','--reverse','--check','-C0',str(patch)],cwd=root,capture_output=True).returncode==0:
            print('SLAM_NETWORK_PATCH_ALREADY_APPLIED')
        else:
            subprocess.run(['git','apply','--check',str(patch)],cwd=root,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
    else:
        assert subprocess.check_output(['git','status','--porcelain'],cwd=root)==b'', 'Preserve user changes before first install'
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()=='d3e50c03fc194272c70cb482fd807a025cf7a5cf'
        def replace(path,old,new,count=1):
            f=root/path;text=f.read_text();assert text.count(old)==count,(path,old)
            f.write_text(text.replace(old,new))
        replace('include/FeatureIO.h','    static bool Active();','    static bool Active();\n    static int InitializationFeatures(int normal_features);')
        replace('src/FeatureIO.cc','#include "ORBextractor.h"','#include "ORBextractor.h"\n#include "FpgaORB.h"')
        replace('src/FeatureIO.cc','selected=="inject","invalid mode"','selected=="inject" || selected=="fpga","invalid mode"')
        replace('src/FeatureIO.cc','bool FeatureIO::Active()',
                'int FeatureIO::InitializationFeatures(int normal_features) {\n'
                '    if(mode=="fpga") { require(normal_features==1000,"FPGA capacity is1000 in both roles"); return 1000; }\n'
                '    return 5*normal_features;\n}\nbool FeatureIO::Active()')
        replace('src/FeatureIO.cc','    if(mode=="inject") mono_left=',
                '    if(mode=="fpga") {\n        static FpgaORB receiver;\n'
                '        mono_left=receiver.extract(root,stats.timestamp_ns,role,extractor,image,keys,descriptors,stats.read_ms,stats.decode_ms);\n'
                '    } else if(mode=="inject") mono_left=')
        replace('src/Tracking.cc','new ORBextractor(5*nFeatures,','new ORBextractor(FeatureIO::InitializationFeatures(nFeatures),',count=2)
        replace('Examples/Monocular/mono_euroc.cc','native|dump|inject]','native|dump|inject|fpga]')
        diff=subprocess.check_output(['git','diff','--no-ext-diff','--','include/FeatureIO.h','src/FeatureIO.cc','src/Tracking.cc','Examples/Monocular/mono_euroc.cc'],cwd=root)
        patch.write_bytes(diff)
    shutil.copyfile(patches/'FpgaORB.h',root/'include/FpgaORB.h')
    shutil.copyfile(workspace/'orb60/linux/protocol.h',root/'include/Orb60Protocol.h')
    # Fixed1000-point PL allocates at most204 points to level0. Keep the
    # initialization100-match gate and geometric tests; match same-octave pairs
    # across the existing pyramid only in FPGA mode. Native behavior is intact.
    multi=patches/'0017-fpga-multiscale-initialization.patch'
    if multi.exists():
        if subprocess.run(['git','apply','--reverse','--check','-C0',str(multi)],cwd=root,capture_output=True).returncode:
            subprocess.run(['git','apply','--check',str(multi)],cwd=root,check=True)
            subprocess.run(['git','apply',str(multi)],cwd=root,check=True)
    else:
        changes=[('include/FeatureIO.h','    static bool Active();','    static bool Active();\n    static bool FPGAActive();'),
                 ('src/FeatureIO.cc','bool FeatureIO::Active()', 'bool FeatureIO::FPGAActive() { return mode=="fpga"; }\nbool FeatureIO::Active()'),
                 ('src/ORBmatcher.cc','#include "ORBmatcher.h"','#include "ORBmatcher.h"\n#include "FeatureIO.h"'),
                 ('src/ORBmatcher.cc','            if(level1>0)\n                continue;',
                  '            // FPGA fixed-budget profile: use same-octave pairs at all levels.\n'
                  '            // Keep100 matches and the original two-view geometric acceptance.\n'
                  '            if(level1>0 && !FeatureIO::FPGAActive())\n                continue;')]
        originals={};updated={}
        for name,old,new in changes:
            path=root/name;text=updated.get(name,path.read_text());originals.setdefault(name,text)
            assert text.count(old)==1,(name,old);updated[name]=text.replace(old,new)
        diff=[]
        for name,text in updated.items():
            (root/name).write_text(text)
            diff.extend(difflib.unified_diff(originals[name].splitlines(True),text.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
        multi.write_text(''.join(diff))
    frame=patches/'0018-fpga-frame-pipeline.patch'
    if frame.exists():
        if subprocess.run(['git','apply','--reverse','--check','-C0',str(frame)],cwd=root,capture_output=True).returncode:
            subprocess.run(['git','apply','--check',str(frame)],cwd=root,check=True)
            subprocess.run(['git','apply',str(frame)],cwd=root,check=True)
        for name in ('FpgaPipeline.h','FpgaReplayInput.h'):
            shutil.copyfile(patches/name,root/'include'/name)
    print('SLAM_NETWORK_PATCH_INSTALLED; native/dump/inject initialization retains5x; FPGA uses1000/1000')


if __name__=='__main__':
    main()
