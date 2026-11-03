"""Generate an isolated, headless KV260 SLAM tree from retained authored patches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def replace(path, old, new, count=1):
    text=path.read_text(encoding='utf-8')
    if text.count(old)!=count:raise ValueError(f'Unsupported source anchor: {path}: {old}')
    path.write_text(text.replace(old,new),encoding='utf-8',newline='\n')


def prepare(output):
    from orb60.demo_bridge.install_rk import patch_feature_io
    from orb60.demo_bridge.patch_shutdown import patch as patch_shutdown
    from orb60.demo_bridge.patch_tracking_diagnostics import patch_tracking,patch_matcher
    output=output.resolve()
    base=ROOT/'rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3'
    if output.exists():raise ValueError('Choose a new output directory; existing builds are never overwritten')
    if output==base or base in output.parents:raise ValueError('Retained source is immutable')
    shutil.copytree(base,output,ignore=shutil.ignore_patterns('.git','build*','*.o','*.so','Vocabulary','dataset-*.txt','*.png','*.jpg','*.pdf','*.bag'))
    originals={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()}
    for installer in ('install_slam_network.py','install_slam_telemetry.py'):
        subprocess.run([sys.executable,str(ROOT/'orb60/scripts'/installer),'--source',str(output),'--workspace',str(ROOT)],check=True,env={**os.environ,'PYTHONUTF8':'1'})
    replace(output/'include/System.h','    void SaveMapDiagnostics(const string &prefix);',
            '    void SaveMapDiagnostics(const string &prefix);\n    void SaveDenseKeyframes(const string &directory);\n    void ExportBridgeMap(const string &directory);')
    methods='''void System::SaveDenseKeyframes(const string &directory) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(5);
    while(!mpLocalMapper->isFinished() || !mpLoopCloser->isFinished() || mpLoopCloser->isRunningGBA()) {
        if(std::chrono::steady_clock::now()>deadline) throw std::runtime_error("Final SLAM workers/BA did not finish");
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    DenseExportAtlas(mpAtlas,directory);
}
void System::ExportBridgeMap(const string &directory) {
    // Only called after the joined Shutdown barrier; export optimized map geometry.
    SaveDenseKeyframes(directory+"_dense");
    ExportBridgeAtlas(mpAtlas,directory);
}

'''
    replace(output/'src/System.cc','#include "System.h"','#include "System.h"\n#include "DenseExport.h"\n#include "BridgeExport.h"\n#include <thread>\n#include <chrono>')
    replace(output/'src/System.cc','int System::GetTrackingState()',methods+'int System::GetTrackingState()')
    replace(output/'src/System.cc','#include <pangolin/pangolin.h>','// KV260 headless build: no OpenGL dependency.')
    replace(output/'include/Map.h','#include <pangolin/pangolin.h>','// Rendering is owned by the separate PS viewer.')
    replace(output/'include/Map.h','GLubyte','unsigned char')
    replace(output/'src/Map.cc','static_cast<GLubyte*>(NULL)','static_cast<unsigned char*>(NULL)',count=3)
    for name,patch in [('src/FeatureIO.cc',patch_feature_io),('src/System.cc',patch_shutdown),('src/Tracking.cc',patch_tracking),('src/ORBmatcher.cc',patch_matcher)]:
        path=output/name;path.write_text(patch(path.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
    if (output/'src/System.cc').read_text(encoding='utf-8').count('ExportBridgeAtlas(mpAtlas,directory+"_full_backup",false);')!=1:
        raise ValueError('Final map backup must be exported exactly once')
    bridge=ROOT/'orb60/demo_bridge/rk'
    for name in ('BridgeFeatures.h','BridgeExport.h','BridgeFrame.h','BridgeDisplay.h','BridgeFinalFrames.h','BridgeTrackingDiagnostics.h','BridgeTrackingDiagnosticsImpl.h'):
        shutil.copy2(bridge/name,output/'include'/name)
    for src in (ROOT/'orb60/dense/slam/DenseExport.h',ROOT/'orb60/dense/slam/DenseFrameTelemetry.h',ROOT/'zynq7015_demo/include/zslam/bridge_wire.hpp'):
        shutil.copy2(src,output/'include'/src.name)
    for name in ('Kv260DepthKeyframes.h','Kv260DepthKeyframesImpl.h'):
        shutil.copy2(ROOT/'orb60/kv260/ps'/name,output/'include'/name)
    replace(output/'src/Tracking.cc','#include "Tracking.h"','#include "Tracking.h"\n#include "Kv260DepthKeyframesImpl.h"')
    replace(output/'src/Tracking.cc','    mpLocalMapper->InsertKeyFrame(pKF);','    KvDepth::publish(pKF);\n    mpLocalMapper->InsertKeyFrame(pKF);')
    text=(bridge/'mono_bridge.cc').read_text(encoding='utf-8')
    text=text.replace('mono_bridge VOCAB RK_YAML CAMERA_ORB_CSV ZYNQ_HOST','mono_kv260 VOCAB KV_YAML CAMERA_ORB_CSV LOCAL_FRONTEND_HOST')
    text=text.replace('BRIDGE_RK_FAILED','KV260_PS_FAILED').replace('Zynq lookup failed','Local feature producer lookup failed').replace('Zynq camera connection failed','Local feature producer connection failed')
    text=text.replace('#include "BridgeFrame.h"','#include "BridgeFrame.h"\n#include "Kv260DepthKeyframes.h"')
    text=text.replace('FeatureIO::Begin(p.stamp);','FeatureIO::Begin(p.stamp);KvDepth::begin(p.frame,p.stamp,p.aux);')
    text=text.replace('bridgeFrame(slam,pose,p,dense);','if(!KvDepth::enabled())bridgeFrame(slam,pose,p,dense);')
    text=text.replace('ack.stamp=p.stamp;peer.send(ack);frames++;','ack.stamp=p.stamp;ack.body=demo::bytes(KvDepth::ack());peer.send(ack);frames++;')
    (output/'Examples/Monocular/mono_kv260.cc').write_text(text,encoding='utf-8',newline='\n')
    # Keep pose storage but omit the optional display implementation. Tracking,
    # LocalMapping, LoopClosing, optimization and all geometric tests are retained.
    for name in ('MapDrawer.h','Viewer.h'):
        shutil.copy2(ROOT/'orb60/kv260/ps'/name,output/'include'/name)
    shutil.copy2(ROOT/'orb60/kv260/ps/CMakeLists.txt',output/'CMakeLists.txt')
    manifest={}
    for p in sorted(output.rglob('*')):
        if p.is_file():
            key=p.relative_to(output).as_posix();digest=hashlib.sha256(p.read_bytes()).hexdigest()
            manifest[key]={'sha256':digest,'retained_before':originals.get(str(p.relative_to(output)))}
    (output/'KV260_SOURCE.json').write_text(json.dumps({'target':'aarch64-linux-gnu','display':'headless','cpu_orb_fallback':False,'files':manifest},indent=2)+'\n')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(prepare(args.output))
