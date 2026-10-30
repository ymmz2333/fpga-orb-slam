"""Author incremental0019, exposing only read-only visualization snapshots."""
import argparse
import difflib
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);a=p.parse_args();original={};updated={}
    def replace(name,old,new):
        text=updated.get(name,(a.source/name).read_text());original.setdefault(name,text)
        assert text.count(old)==1,(name,old);updated[name]=text.replace(old,new)
    replace('include/System.h','class Verbose','struct OrbTelemetryData;\n\nclass Verbose')
    replace('include/System.h','    void SaveMapDiagnostics(const string &prefix);',
            '    void SaveMapDiagnostics(const string &prefix);\n    void GetVisualizationSnapshot(OrbTelemetryData& out,bool include_map);')
    replace('src/System.cc','#include "System.h"','#include "System.h"\n#include "OrbTelemetry.h"')
    replace('src/System.cc','int System::GetTrackingState()', '''void System::GetVisualizationSnapshot(OrbTelemetryData& out,bool include_map)
{
    out.state=GetTrackingState();
    Map* map=mpAtlas->GetCurrentMap();
    if(!map)return;
    out.map_id=map->GetId();
    const auto& keys=mpTracker->mCurrentFrame.mvKeys;
    const auto& matches=mpTracker->mCurrentFrame.mvpMapPoints;
    const auto& outliers=mpTracker->mCurrentFrame.mvbOutlier;
    out.features.reserve(keys.size());
    for(size_t i=0;i<keys.size();++i) {
        bool tracked=i<matches.size()&&matches[i]&&i<outliers.size()&&!outliers[i];
        out.features.push_back({keys[i].pt.x,keys[i].pt.y,keys[i].octave,tracked});
    }
    if(!include_map)return;
    // Same point/pose APIs as MapDrawer. Skip a busy map rather than delaying tracking.
    unique_lock<mutex> lock(map->mMutexMapUpdate,std::try_to_lock);
    if(!lock.owns_lock())return;
    out.map_full=true;
    for(MapPoint* point:map->GetAllMapPoints()) {
        if(!point||point->isBad())continue;
        Eigen::Vector3f xyz=point->GetWorldPos();
        if(xyz.allFinite())out.points.push_back({point->mnId,xyz});
        if(out.points.size()>=20000)break;
    }
    for(KeyFrame* key:map->GetAllKeyFrames()) {
        if(!key||key->isBad())continue;
        Eigen::Matrix4f pose=key->GetPoseInverse().matrix();
        if(pose.allFinite())out.keyframes.push_back({key->mnId,pose});
        if(out.keyframes.size()>=2000)break;
    }
}

int System::GetTrackingState()''')
    name='Examples/Monocular/mono_euroc.cc'
    replace(name,'#include<FpgaReplayInput.h>','#include<FpgaReplayInput.h>\n#include<OrbTelemetry.h>')
    replace(name,'    string featureMode="native", featureDirectory;',
            '    string featureMode="native", featureDirectory, telemetryDirectory;\n    bool telemetryRecord=false;')
    replace(name,'        else if(argument == "--feature-mode" || argument == "--feature-dir")',
            '        else if(argument == "--telemetry-record") telemetryRecord=true;\n'
            '        else if(argument == "--telemetry-dir") {\n'
            '            if(i+1>=argc)return 1;telemetryDirectory=argv[++i];\n        }\n'
            '        else if(argument == "--feature-mode" || argument == "--feature-dir")')
    replace(name,'    double t_resize = 0.f;',
            '    std::unique_ptr<ORB_SLAM3::OrbTelemetry> telemetry;\n'
            '    if(!telemetryDirectory.empty()) telemetry.reset(new ORB_SLAM3::OrbTelemetry(telemetryDirectory,telemetryRecord));\n'
            '    double t_resize = 0.f;')
    replace(name,'            SLAM.TrackMonocular(im,tframe);', '            auto currentTcw=SLAM.TrackMonocular(im,tframe);')
    replace(name,'            vTimesTrack[ni]=ttrack;',
            '            vTimesTrack[ni]=ttrack;\n'
            '            if(telemetry) telemetry->capture(SLAM,im,currentTcw,uint64_t(ni),timestampNs,\n'
            '                ORB_SLAM3::FeatureIO::Stats(),ttrack*1000.,ni==nImages[seq]-1);')
    replace(name,'    // Stop all threads', '    if(telemetry)telemetry->finish();\n    // Stop all threads')
    diff=[]
    for name,text in updated.items():
        diff.extend(difflib.unified_diff(original[name].splitlines(True),text.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    (a.workspace/'rk3588/orbslam3_cpu_baseline/patches/0019-slam-visualization-telemetry.patch').write_text(''.join(diff))
    print('READ_ONLY_TELEMETRY_PATCH_AUTHORED')


if __name__=='__main__':main()
