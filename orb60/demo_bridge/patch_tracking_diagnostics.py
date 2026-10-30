"""Strict, idempotent observation-only patch for the isolated deployed SLAM."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

MARKER='BRIDGE_TRACKING_DIAGNOSTICS_V1'

def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unexpected diagnostic anchor: '+old[:100])
    return text.replace(old,new)

def change_function(text,signature,transform):
    start=text.index(signature)
    # Mask comments and literals so their braces do not affect the C++ boundary.
    masked=re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m[0]),text,flags=re.S)
    opening=masked.index('{',start);depth=0
    for i in range(opening,len(masked)):
        depth+=(masked[i]=='{')-(masked[i]=='}')
        if depth==0:
            body=text[start:i+1];return text[:start]+transform(body)+text[i+1:]
    raise ValueError('Unterminated C++ function')

def decisions(body,stage):
    pos=body.index('{')+1
    body=body[:pos]+'\n    int bridge_matches=-1,bridge_inliers=-1;\n'+body[pos:]
    return re.sub(r'\breturn\s+([^;]+);',lambda m:'return BridgeDiag::decision("'+stage+'",('+m[1]+'),bridge_matches,bridge_inliers);',body)

def patch_tracking(text):
    if MARKER in text:return text
    text=once(text,'#include "Tracking.h"','#include "Tracking.h"\n#include "BridgeTrackingDiagnosticsImpl.h"\n// '+MARKER)
    def track(body):
        pos=body.index('{')+1
        return body[:pos]+'''
    auto bridge_exit=BridgeDiag::onExit([&](){
        if(!BridgeDiag::active())return;
        Map* map=mpAtlas->GetCurrentMap();
        BridgeDiag::event("tracking_exit",{{"state",mState},{"map_id",map?double(map->GetId()):-1.}});
    });
    if(BridgeDiag::active()){
        Map* map=mpAtlas->GetCurrentMap();
        BridgeDiag::event("tracking_enter",{{"state",mState},{"slam_frame_id",double(mCurrentFrame.mnId)},
          {"map_id",map?double(map->GetId()):-1.},{"map_keyframes",map?double(map->KeyFramesInMap()):0.},
          {"frame_delta_ms",(mCurrentFrame.mTimeStamp-mLastFrame.mTimeStamp)*1000}});
    }
'''+body[pos:]
    text=change_function(text,'void Tracking::Track()',track)
    def reference(body):
        body=decisions(body,'reference_result')
        body=once(body,'int nmatches = matcher.SearchByBoW(mpReferenceKF,mCurrentFrame,vpMapPointMatches);',
                       'int nmatches = matcher.SearchByBoW(mpReferenceKF,mCurrentFrame,vpMapPointMatches);\n    bridge_matches=nmatches;')
        return once(body,'    if (mSensor == System::IMU_MONOCULAR',
                         '    bridge_inliers=nmatchesMap;\n    if (mSensor == System::IMU_MONOCULAR')
    text=change_function(text,'bool Tracking::TrackReferenceKeyFrame()',reference)
    def motion(body):
        body=decisions(body,'motion_result')
        body=once(body,'int nmatches = matcher.SearchByProjection(mCurrentFrame,mLastFrame,th,mSensor==System::MONOCULAR || mSensor==System::IMU_MONOCULAR);',
                       'int nmatches = matcher.SearchByProjection(mCurrentFrame,mLastFrame,th,mSensor==System::MONOCULAR || mSensor==System::IMU_MONOCULAR);\n    bridge_matches=nmatches;')
        body=once(body,'nmatches = matcher.SearchByProjection(mCurrentFrame,mLastFrame,2*th,mSensor==System::MONOCULAR || mSensor==System::IMU_MONOCULAR);',
                       'nmatches = matcher.SearchByProjection(mCurrentFrame,mLastFrame,2*th,mSensor==System::MONOCULAR || mSensor==System::IMU_MONOCULAR);\n        bridge_matches=nmatches;')
        return once(body,'    if(mbOnlyTracking)','    bridge_inliers=nmatchesMap;\n    if(mbOnlyTracking)')
    text=change_function(text,'bool Tracking::TrackWithMotionModel()',motion)
    def local(body):
        body=decisions(body,'local_result')
        body=once(body,'    int inliers;','    bridge_matches=aux1;\n    int inliers;')
        return once(body,'    mpLocalMapper->mnMatchesInliers=mnMatchesInliers;',
          '''    bridge_inliers=mnMatchesInliers;
    BridgeDiag::event("local_gate",{{"inliers",mnMatchesInliers},{"recent_relocalization",mCurrentFrame.mnId<mnLastRelocFrameId+mMaxFrames?1.:0.},
      {"state",mState},{"standard_monocular_minimum",30},{"recent_relocalization_minimum",50}});
    mpLocalMapper->mnMatchesInliers=mnMatchesInliers;''')
    text=change_function(text,'bool Tracking::TrackLocalMap()',local)
    def relocalize(body):
        anchor='    if(vpCandidateKFs.empty())'
        body=once(body,anchor,'    BridgeDiag::event("relocalization_candidates",{{"count",double(vpCandidateKFs.size())}});\n'+anchor)
        anchor='int nmatches = matcher.SearchByBoW(pKF,mCurrentFrame,vvpMapPointMatches[i]);'
        body=once(body,anchor,anchor+'\n            BridgeDiag::event("relocalization_bow",{{"keyframe_id",double(pKF->mnId)},{"matches",nmatches},{"minimum",15}});')
        anchor='bool bTcw = pSolver->iterate(5,bNoMore,vbInliers,nInliers, eigTcw);'
        body=once(body,anchor,anchor+'\n            BridgeDiag::event("relocalization_pnp",{{"keyframe_id",double(vpCandidateKFs[i]->mnId)},{"pose_found",bTcw?1.:0.},{"ransac_inliers",bTcw?double(nInliers):-1.},{"exhausted",bNoMore?1.:0.}});')
        pattern=r'((?:int )?nGood = Optimizer::PoseOptimization\(&mCurrentFrame\);)'
        body,n=re.subn(pattern,r'\1\n                BridgeDiag::event("relocalization_optimized",{{"keyframe_id",double(vpCandidateKFs[i]->mnId)},{"inliers",nGood},{"accept_minimum",50}});',body)
        if n!=3:raise ValueError('Unexpected relocalization optimization count')
        body=once(body,'    if(!bMatch)','    BridgeDiag::event("relocalization_result",{{"accepted",bMatch?1.:0.}});\n    if(!bMatch)')
        return body
    text=change_function(text,'bool Tracking::Relocalization()',relocalize)
    def new_map(body):
        anchor='    mpAtlas->CreateNewMap();'
        return once(body,anchor,'''    if(BridgeDiag::active()){Map* old=mpAtlas->GetCurrentMap();BridgeDiag::event("new_map",{{"previous_map_id",old?double(old->GetId()):-1.},{"tracking_state",mState}});}
'''+anchor+'''
    if(BridgeDiag::active()){Map* current=mpAtlas->GetCurrentMap();BridgeDiag::event("new_map_created",{{"map_id",current?double(current->GetId()):-1.}});}
''')
    return change_function(text,'void Tracking::CreateMapInAtlas()',new_map)

def patch_matcher(text):
    if MARKER in text:return text
    text=once(text,'#include "ORBmatcher.h"','#include "ORBmatcher.h"\n#include "BridgeTrackingDiagnostics.h"\n// '+MARKER)
    specs=[
      ('int ORBmatcher::SearchByBoW(KeyFrame* pKF,Frame &F,','bow_frame','double(pKF->mnId)',True),
      ('int ORBmatcher::SearchForInitialization(Frame &F1, Frame &F2,','initialization_pairs','-1.',True),
      ('int ORBmatcher::SearchByProjection(Frame &CurrentFrame, const Frame &LastFrame,','motion_projection','-1.',True),
      ('int ORBmatcher::SearchByProjection(Frame &CurrentFrame, KeyFrame *pKF,','relocalization_projection','double(pKF->mnId)',True),
      ('int ORBmatcher::SearchByProjection(Frame &F, const vector<MapPoint*> &vpMapPoints,','local_projection','-1.',False)]
    for signature,stage,kf,orientation in specs:
        def transform(body,stage=stage,kf=kf,orientation=orientation):
            if orientation:
                anchor='        if(mbCheckOrientation)'
                # Last occurrence is the final orientation histogram filter.
                at=body.rfind(anchor)
                if at<0:raise ValueError('No final orientation filter')
                body=body[:at]+'        const int bridge_before_orientation=nmatches;\n'+body[at:]
            fields='{{"matches_before_orientation",'+('bridge_before_orientation' if orientation else 'nmatches')+'},{"matches_after_orientation",nmatches},{"keyframe_id",'+kf+'}'
            if 'Projection' in signature:fields+=',{"search_factor",th}'
            fields+='}'
            return once(body,'        return nmatches;','        BridgeDiag::event("'+stage+'",'+fields+');\n        return nmatches;')
        text=change_function(text,signature,transform)
    return text

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
    root=a.source;manifest={}
    for rel,patch in [('src/Tracking.cc',patch_tracking),('src/ORBmatcher.cc',patch_matcher)]:
        path=root/rel;before=path.read_bytes();after=patch(before.decode()).encode()
        backup=path.with_name(path.name+'.before_tracking_diagnostics')
        if not backup.exists():backup.write_bytes(before)
        path.write_bytes(after);manifest[rel]=dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest())
    for name in ('BridgeTrackingDiagnostics.h','BridgeTrackingDiagnosticsImpl.h'):
        shutil.copy2(Path(__file__).parent/'rk'/name,root/'include'/name)
    (root/'TRACKING_DIAGNOSTICS_PATCH.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(MARKER,'PATCHED; all matching thresholds and return expressions preserved')

if __name__=='__main__':main()
