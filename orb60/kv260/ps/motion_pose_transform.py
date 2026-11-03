"""Bounded PS policy change; keep final solver and geometric acceptance intact."""
def transform(source):
    start='bool Tracking::TrackWithMotionModel()';end='bool Tracking::TrackLocalMap()'
    if source.count(start)!=1 or source.count(end)!=1:raise ValueError('Unreviewed mono tracking boundary')
    a=source.index(start);b=source.index(end,a);motion=source[a:b]
    old='    Optimizer::PoseOptimization(&mCurrentFrame);'
    if motion.count(old)!=1:raise ValueError('One preliminary motion pose solve required')
    replacement='''    const bool defer_motion_pose=KvMotionPose::defer(mSensor==System::MONOCULAR&&!mpAtlas->isImuInitialized(),mbOnlyTracking,mState==OK,mnMatchesInliers,nmatches,mCurrentFrame.mnId);
    if(defer_motion_pose)BridgeDiag::event("motion_pose_deferred",{{"projected_matches",nmatches},{"previous_inliers",mnMatchesInliers}});
    if(!defer_motion_pose)Optimizer::PoseOptimization(&mCurrentFrame);'''
    changed=source[:a]+motion.replace(old,replacement)+source[b:]
    final='''    if (!mpAtlas->isImuInitialized())
        Optimizer::PoseOptimization(&mCurrentFrame);
    else'''
    selected='''    if (!mpAtlas->isImuInitialized()) {
        Optimizer::PoseOptimization(&mCurrentFrame);
        KvMotionPose::final_pose(mCurrentFrame.mnId);
    }
    else'''
    if changed.count(final)!=1:raise ValueError('One unchanged final mono solve required')
    changed=changed.replace(final,selected)
    include='#include "MotionPosePolicy.h"\n';changed=include+changed
    recovered=changed[len(include):].replace(selected,final).replace(replacement,old)
    if recovered!=source:raise ValueError('Unexpected matching or geometry change')
    return changed
