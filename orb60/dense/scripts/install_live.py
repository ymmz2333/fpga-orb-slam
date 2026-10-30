"""Install optional live keyframe sidecar; preserve existing accepted sources/binaries."""
import argparse
from pathlib import Path
import shutil
import json
import hashlib


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path)
    p.add_argument('--dense',required=True,type=Path);p.add_argument('--snapshot',required=True,type=Path)
    a=p.parse_args();changes={
        'include/System.h':('    void SaveDenseKeyframes(const string &directory);',
                            '    void SaveDenseKeyframes(const string &directory);\n    void ExportLiveDenseSnapshot(const string &directory);'),
        'src/System.cc':('int System::GetTrackingState()',
            'void System::ExportLiveDenseSnapshot(const string &directory) { DenseLiveExportAtlas(mpAtlas,directory); }\n\nint System::GetTrackingState()'),
        'Examples/Monocular/mono_euroc.cc':('            vTimesTrack[ni]=ttrack;',
            '            vTimesTrack[ni]=ttrack;\n            if(const char* live=std::getenv("ORB60_DENSE_LIVE_DIR")) SLAM.ExportLiveDenseSnapshot(live);')}
    if 'void System::ExportLiveDenseSnapshot' not in (a.source/'src/System.cc').read_text():
        a.snapshot.mkdir(parents=True,exist_ok=False);manifest={}
        for name in [*changes,'Examples/Monocular/mono_euroc','lib/libORB_SLAM3.so']:
            dst=a.snapshot/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a.source/name,dst)
            manifest[name]=hashlib.sha256(dst.read_bytes()).hexdigest()
        (a.snapshot/'sha256.json').write_text(json.dumps(manifest,indent=2))
        for name,(old,new) in changes.items():
            path=a.source/name;text=path.read_text()
            if text.count(old)!=1:raise ValueError('Unexpected live install anchor: '+name)
            text=text.replace(old,new)
            if name=='src/System.cc':text=text.replace('#include "DenseExport.h"','#include "DenseExport.h"\n#include "DenseLiveExport.h"')
            path.write_text(text)
    shutil.copy2(a.dense/'slam/DenseLiveExport.h',a.source/'include/DenseLiveExport.h')
    print('LIVE_KEYFRAME_SIDECAR_INSTALLED')


if __name__=='__main__':main()
