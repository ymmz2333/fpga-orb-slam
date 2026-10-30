"""Optional final-map export; back up accepted SLAM sources and binaries first."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser()
p.add_argument("--source", required=True, type=Path)
p.add_argument("--dense", required=True, type=Path)
p.add_argument("--snapshot", required=True, type=Path)
a = p.parse_args()
changes = {
    "include/System.h": ("    void SaveMapDiagnostics(const string &prefix);",
                         "    void SaveMapDiagnostics(const string &prefix);\n    void SaveDenseKeyframes(const string &directory);"),
    "src/System.cc": ("int System::GetTrackingState()", '''void System::SaveDenseKeyframes(const string &directory)
{
    // Shutdown currently requests finish but does not join the worker threads.
    // Only snapshot a final, stable map; an unfinished BA is never called final.
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(5);
    while(!mpLocalMapper->isFinished() || !mpLoopCloser->isFinished() || mpLoopCloser->isRunningGBA()) {
        if(std::chrono::steady_clock::now()>deadline) throw std::runtime_error("Final SLAM optimization did not finish");
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    DenseExportAtlas(mpAtlas,directory);
}

int System::GetTrackingState()'''),
    "Examples/Monocular/mono_euroc.cc": ('    SLAM.SaveMapDiagnostics("Diagnostics");',
                                      '    SLAM.SaveMapDiagnostics("Diagnostics");\n    if(const char* directory=std::getenv("ORB60_DENSE_EXPORT")) SLAM.SaveDenseKeyframes(directory);')}
already = "void System::SaveDenseKeyframes" in (a.source / "src/System.cc").read_text()
if not already:
    a.snapshot.mkdir(parents=True, exist_ok=False)
    saved = {}
    for name in [*changes, "Examples/Monocular/mono_euroc", "lib/libORB_SLAM3.so"]:
        target = a.snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a.source / name, target)
        saved[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (a.snapshot / "sha256.json").write_text(json.dumps(saved, indent=2)+"\n")
    for name, (old, new) in changes.items():
        path = a.source / name
        text = path.read_text()
        if text.count(old) != 1:
            raise ValueError("Unexpected source anchor: " + name)
        text = text.replace(old, new)
        if name == "src/System.cc":
            text = text.replace('#include "System.h"', '#include "System.h"\n#include "DenseExport.h"\n#include <chrono>\n#include <thread>')
        path.write_text(text)
shutil.copy2(a.dense / "slam/DenseExport.h", a.source / "include/DenseExport.h")
print("FINAL_KEYFRAME_EXPORT_INSTALLED_WITH_BACKUP")
