"""Explicit current mapping target; retained performance trials keep old gates."""
def evaluate(profile,checks,continuity,timings,*,profiling,kernel_tainted,last_pose_valid):
    if profile not in ('throughput30','stable_map_handoff','stable_map_5fps','stable_map_5fps_tail84'):raise ValueError('Explicit known mapping acceptance profile required')
    failures=[]
    if profiling:failures.append('Profiling enabled: diagnostic run, no acceptance')
    if profile!='stable_map_5fps_tail84' and checks['valid_after_initialization']<.98:failures.append('Tracking stability below98% after initialization')
    if continuity['status']!='SINGLE_MAP_CREATION_PASS':failures.append('Whole-video SLAM created multiple maps or its map creation record is missing')
    if kernel_tainted&128:failures.append('Kernel previously reported an Oops; repeat after clean boot required')
    if profile=='throughput30' and timings['all_geometry_fps']<=30:failures.append('Whole-video geometry throughput is not above30FPS')
    if profile in ('stable_map_handoff','stable_map_5fps') and not last_pose_valid:failures.append('Final source frame has no valid pose')
    if profile in ('stable_map_5fps','stable_map_5fps_tail84') and timings['all_geometry_fps']<5:failures.append('Whole-video geometry throughput is below5FPS')
    if profile=='stable_map_5fps_tail84':
        segments=continuity.get('tracking_loss_segments');frames=checks.get('frames')
        if not isinstance(segments,list) or type(frames) is not int or frames<=84:
            failures.append('Full frame count and explicit loss segments required for accepted tail profile')
        elif segments:
            if len(segments)!=1 or not 1<=segments[0]['frames']<=84 or segments[0]['last_source_frame']!=frames-1 or segments[0]['first_source_frame']!=frames-segments[0]['frames']:
                failures.append('Loss exceeds the user-accepted final continuous84frame tail')
        elif not last_pose_valid:failures.append('Missing last pose is inconsistent with the empty loss record')
    success='ACTUAL_TWO_BOARD_DPU_GPU_PASS' if profile=='throughput30' else 'ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS'
    return dict(status='FAILED_TARGET_GATES' if failures else success,failed_gates=failures,acceptance_profile=profile,
                scope='Concurrent mapping component only; 7015 map import/localization and direct-cable acceptance are separate')
