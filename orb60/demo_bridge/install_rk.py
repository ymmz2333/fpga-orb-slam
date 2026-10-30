"""Prepare an isolated RK source copy and explicit patches, never edit retained SLAM."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
from .patch_shutdown import patch as patch_shutdown
from .patch_tracking_diagnostics import patch_tracking,patch_matcher


def patch_feature_io(text):
    if '#include "BridgeFeatures.h"' in text:
        return text
    replacements = [
        ('#include "FpgaORB.h"', '#include "FpgaORB.h"\n#include "BridgeFeatures.h"'),
        ('selected=="fpga-pipeline","invalid mode"', 'selected=="fpga-pipeline" || selected=="fpga-camera","invalid mode"'),
        ('return mode=="fpga" || PipelineActive();', 'return mode=="fpga" || mode=="fpga-camera" || PipelineActive();'),
        ('    if(PipelineActive()) {\n        mono_left=',
         '    if(mode=="fpga-camera") {\n        mono_left=BridgeFeatures::consume(stats.timestamp_ns,image,extractor,keys,descriptors,stats.read_ms,stats.decode_ms);\n    } else if(PipelineActive()) {\n        mono_left=')]
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('Unsupported RK FeatureIO anchor: ' + old)
        text = text.replace(old, new)
    return text


def prepare(source, output, workspace):
    source, output, workspace = map(lambda p: Path(p).resolve(), (source, output, workspace))
    if output == source or source in output.parents or output.exists():
        raise ValueError('Choose a new isolated sibling output directory')
    bridge = workspace / 'orb60/demo_bridge'
    feature = (source / 'src/FeatureIO.cc').read_text()
    updated_feature = patch_feature_io(feature)
    system_h = (source / 'include/System.h').read_text()
    system_cc = (source / 'src/System.cc').read_text()
    if 'GetVisualizationSnapshot' not in system_h or 'SaveDenseKeyframes' not in system_h:
        raise ValueError('Use the retained FPGA pipeline + visualization + final export source as input')
    old = '    void SaveDenseKeyframes(const string &directory);'
    if system_h.count(old) != 1:
        raise ValueError('Unknown final export declaration')
    updated_h = system_h.replace(old, old + '\n    void ExportBridgeMap(const string &directory);')
    anchor = 'int System::GetTrackingState()'
    if system_cc.count(anchor) != 1:
        raise ValueError('Unknown System.cc anchor')
    method = '''void System::ExportBridgeMap(const string &directory) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(5);
    while(!mpLocalMapper->isFinished() || !mpLoopCloser->isFinished() || mpLoopCloser->isRunningGBA()) {
        if(std::chrono::steady_clock::now()>deadline) throw std::runtime_error("Final SLAM workers/BA did not finish");
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    std::cout << "BRIDGE_FULL_BACKUP_BEGIN" << std::endl;
    ExportBridgeAtlas(mpAtlas,directory+"_full_backup",false);
    std::cout << "BRIDGE_FULL_BACKUP_DONE" << std::endl;
    ExportBridgeAtlas(mpAtlas,directory);
}

'''
    updated_cc = system_cc.replace('#include "System.h"', '#include "System.h"\n#include "BridgeExport.h"\n#include <thread>\n#include <chrono>').replace(anchor, method + anchor)
    updated_cc = patch_shutdown(updated_cc)
    # A full independent source copy avoids source edits and ABI interposition in the retained build.
    shutil.copytree(source, output, ignore=shutil.ignore_patterns('.git', 'build', 'build*', '*.o', '*.so', 'Vocabulary'))
    for folder in ('Vocabulary',):
        if (source / folder).exists():
            (output / folder).symlink_to(source / folder, target_is_directory=True)
    changes = {'src/FeatureIO.cc': (feature, updated_feature), 'include/System.h': (system_h, updated_h), 'src/System.cc': (system_cc, updated_cc)}
    diff, manifest = [], {}
    for name, (before, after) in changes.items():
        (output / name).write_text(after)
        manifest[name] = dict(before=hashlib.sha256(before.encode()).hexdigest(), after=hashlib.sha256(after.encode()).hexdigest())
        diff += difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/' + name, tofile='b/' + name)
    for name,patch in [('src/Tracking.cc',patch_tracking),('src/ORBmatcher.cc',patch_matcher)]:
        path=output/name;before=path.read_text();after=patch(before);path.write_text(after)
        manifest[name]=dict(before=hashlib.sha256(before.encode()).hexdigest(),after=hashlib.sha256(after.encode()).hexdigest())
        diff+=difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name)
    for name in ('BridgeFeatures.h', 'BridgeExport.h', 'BridgeFrame.h', 'BridgeDisplay.h','BridgeFinalFrames.h',
                 'BridgeTrackingDiagnostics.h','BridgeTrackingDiagnosticsImpl.h'):
        shutil.copy2(bridge / 'rk' / name, output / 'include' / name)
    shutil.copy2(workspace / 'zynq7015_demo/include/zslam/bridge_wire.hpp', output / 'include/bridge_wire.hpp')
    shutil.copy2(bridge / 'rk/mono_bridge.cc', output / 'Examples/Monocular/mono_bridge.cc')
    shutil.copy2(workspace / 'orb60/dense/slam/DenseFrameTelemetry.h', output / 'include/DenseFrameTelemetry.h')
    # Existing targets keep their build behavior. Only add our executable.
    with (output / 'CMakeLists.txt').open('a') as f:
        f.write('\nadd_executable(mono_bridge Examples/Monocular/mono_bridge.cc)\ntarget_link_libraries(mono_bridge ${PROJECT_NAME})\nset_target_properties(mono_bridge PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/demo_bin")\n')
    (output / 'DEMO_BRIDGE.patch').write_text(''.join(diff))
    (output / 'DEMO_BRIDGE_SOURCE.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    a = p.parse_args()
    prepare(a.source, a.output, a.workspace)
    print('ISOLATED_RK_SOURCE_PREPARED; build target mono_bridge serially')
