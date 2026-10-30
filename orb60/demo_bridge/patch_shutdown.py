"""Quiesce isolated ORB-SLAM3 workers before Atlas PreSave/serialization."""
import argparse,hashlib,json
from pathlib import Path

SHUTDOWN='''void System::Shutdown()
{
    { unique_lock<mutex> lock(mMutexReset); mbShutDown = true; }
    std::cout << "BRIDGE_SHUTDOWN_WAIT_BEGIN" << std::endl;
    mpLocalMapper->RequestFinish();
    mpLoopCloser->RequestFinish();
    if(mpViewer) mpViewer->RequestFinish();
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(5);
    while(!mpLocalMapper->isFinished() || !mpLoopCloser->isFinished() ||
          mpLoopCloser->isRunningGBA() || (mpViewer && !mpViewer->isFinished())) {
        if(std::chrono::steady_clock::now()>deadline)
            throw std::runtime_error("Shutdown workers/GBA did not quiesce within 300 seconds");
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    if(mptLocalMapping && mptLocalMapping->joinable()) mptLocalMapping->join();
    if(mptLoopClosing && mptLoopClosing->joinable()) mptLoopClosing->join();
    std::cout << "BRIDGE_SHUTDOWN_WORKERS_FINISHED" << std::endl;
    if(!mStrSaveAtlasToFile.empty()) {
        std::cout << "BRIDGE_ATLAS_SAVE_BEGIN" << std::endl;
        SaveAtlas(FileType::BINARY_FILE);
        std::cout << "BRIDGE_ATLAS_SAVE_DONE" << std::endl;
    }
#ifdef REGISTER_TIMES
    mpTracker->PrintTimeStats();
#endif
    std::cout << "BRIDGE_SHUTDOWN_DONE" << std::endl;
}

'''

def patch(text):
    start=text.index('void System::Shutdown()')
    end=text.index('bool System::isShutDown()',start)
    if '#include <thread>' not in text:text=text.replace('#include "System.h"','#include "System.h"\n#include <thread>\n#include <chrono>')
    start=text.index('void System::Shutdown()');end=text.index('bool System::isShutDown()',start)
    text=text[:start]+SHUTDOWN+text[end:]
    if 'BRIDGE_FULL_BACKUP_BEGIN' not in text and 'ExportBridgeAtlas(mpAtlas,directory);' in text:
        text=text.replace('ExportBridgeAtlas(mpAtlas,directory);','std::cout << "BRIDGE_FULL_BACKUP_BEGIN" << std::endl;\n    ExportBridgeAtlas(mpAtlas,directory+"_full_backup",false);\n    std::cout << "BRIDGE_FULL_BACKUP_DONE" << std::endl;\n    ExportBridgeAtlas(mpAtlas,directory);')
    if '#include "BridgeFinalFrames.h"' not in text:text=text.replace('#include "BridgeExport.h"','#include "BridgeExport.h"\n#include "BridgeFinalFrames.h"')
    if 'ExportBridgeFinalFrames(mpTracker' not in text:
        text=text.replace('ExportBridgeAtlas(mpAtlas,directory);','ExportBridgeAtlas(mpAtlas,directory);\n    ExportBridgeFinalFrames(mpTracker,mpAtlas->GetCurrentMap(),directory+"/final_frames.csv");')
    return text

def main():
    p=argparse.ArgumentParser();p.add_argument('system',type=Path);a=p.parse_args();before=a.system.read_bytes()
    backup=a.system.with_name('System.before_quiescent_shutdown.cc')
    if not backup.exists():backup.write_bytes(before)
    after=patch(before.decode()).encode();a.system.write_bytes(after)
    a.system.with_name('shutdown_patch.json').write_text(json.dumps(dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest(),scope='Isolated RK source only; no retained baseline changes'),indent=2)+'\n')
    print('QUIESCENT_SHUTDOWN_PATCHED')

if __name__=='__main__':main()
