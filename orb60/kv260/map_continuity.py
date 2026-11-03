"""Read-only whole-video Atlas creation and tracking-loss audit."""
import re

def audit(actual, native_log):
    events=[]; frame=None
    for line in native_log.splitlines():
        m=re.search(r'FPGA_ORB_NET frame=(\d+)\b',line)
        if m:frame=int(m[1])-1 # native diagnostic counter is one-based
        m=re.search(r'^Creation of new map with id:\s*(\d+)\s*$',line.strip())
        if m:events.append(dict(map_id=int(m[1]),last_completed_source_frame=frame))
    first=next((i for i,r in enumerate(actual) if int(r['pose_valid'])),None)
    losses=[];begin=None
    if first is not None:
        for i in range(first,len(actual)+1):
            bad=i<len(actual) and not int(actual[i]['pose_valid'])
            if bad and begin is None:begin=i
            if not bad and begin is not None:
                losses.append(dict(first_source_frame=begin,last_source_frame=i-1,frames=i-begin));begin=None
    # Even if a later merge leaves one exported map, an intermediate reset fails.
    passed=first is not None and len(events)==1
    return dict(status='SINGLE_MAP_CREATION_PASS' if passed else 'MAP_CONTINUITY_FAILED',
                maps_created=events,tracking_loss_segments=losses,
                scope='Atlas creation log plus per-frame pose validity; not ground-truth trajectory accuracy')
