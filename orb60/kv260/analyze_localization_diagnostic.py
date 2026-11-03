"""Offline descriptor-recall diagnosis from physical PL samples and saved map poses.

Saved final SLAM poses are a same-run diagnostic reference, not ground truth and
never injected into the actual localizer. No ORB extraction or pose output here.
"""
import argparse,json,zlib
from pathlib import Path
import cv2
import numpy as np
from .run_network_system import load,rows,digest,save
from orb60.demo_bridge.calibration import read


def distinct_matches(query,train,landmark_ids):
    matcher=cv2.BFMatcher(cv2.NORM_HAMMING)
    neighbors=matcher.knnMatch(query,train,k=min(64,len(train)))
    result=[]
    for i,ranked in enumerate(neighbors):
        while ranked and len({landmark_ids[m.trainIdx] for m in ranked})<2 and len(ranked)<len(train):
            ranked=matcher.knnMatch(query[i:i+1],train,k=min(len(train),len(ranked)*4))[0]
        if not ranked:continue
        best=ranked[0];pid=landmark_ids[best.trainIdx]
        second=next((m.distance for m in ranked if landmark_ids[m.trainIdx]!=pid),257)
        if best.distance<=64 and best.distance*5<second*4:result.append((int(best.distance),pid,i))
    used=set();answer=[]
    for d,pid,i in sorted(result):
        if pid not in used:used.add(pid);answer.append((i,pid,d))
    return answer


def analyze(session,samples,output):
    session,samples,output=map(Path,(session,samples,output));receipt=load(samples/'RESULT.json')
    if receipt['status']!='ACTUAL_SAME_INPUT_PHYSICAL_PL_DIAGNOSTIC_SAMPLES_CAPTURED':raise ValueError('Actual same-input PL samples required')
    folder=session/'handoff/map';camera=read((folder/'camera_orb.csv').read_bytes())
    if receipt['map_version']!=load(session/'handoff/HANDOFF.json')['map']['version']:raise ValueError('Diagnostic map differs')
    points,obs=rows(folder/'points.csv'),rows(folder/'observations.csv');ids=[int(p['point_id']) for p in points]
    lookup={pid:i for i,pid in enumerate(ids)};xyz=np.array([[float(p[k]) for k in ('x','y','z')] for p in points])
    reps=np.frombuffer((folder/'representative_descriptors.bin').read_bytes(),np.uint8).reshape(-1,32).copy()
    all_desc=np.frombuffer((folder/'observation_descriptors.bin').read_bytes(),np.uint8).reshape(-1,32).copy()
    obs_ids=[int(o['point_id']) for o in obs]
    key_order={int(r['keyframe_id']):i for i,r in enumerate(rows(folder/'keyframes.csv'))}
    history={pid:[] for pid in ids}
    for i,o in enumerate(obs):history[int(o['point_id'])].append(i)
    kept=sorted(i for indices in history.values() for i in sorted(indices,key=lambda n:key_order[int(obs[n]['keyframe_id'])])[-8:])
    bounded_desc=np.ascontiguousarray(np.concatenate((reps,all_desc[kept]),axis=0));bounded_ids=ids+[obs_ids[i] for i in kept]
    poses={int(p['slam_timestamp_ns']):p for p in rows(session/'mapping/tracking/map/final_frames.csv')}
    timed=rows(session/'native_localization/app/timing.part000000.csv')
    k=np.array([[camera['fx'],0,camera['cx']],[0,camera['fy'],camera['cy']],[0,0,1.]])
    distortion=np.array([camera['d%d'%i] for i in range(5)])
    scale=np.ones(8,np.float32)
    for i in range(1,8):scale[i]=scale[i-1]*np.float32(1.2)
    results=[]
    for item in receipt['samples']:
        path=samples/item['payload'];data=path.read_bytes()
        if digest(path)!=item['payload_sha256']:raise ValueError('Physical sample changed')
        n=item['count'];record=data[128:128+n*64]
        if zlib.crc32(record)!=item['record_crc']:raise ValueError('Physical record CRC differs')
        raw=np.frombuffer(record,np.uint8).reshape(n,64);words=np.frombuffer(record,'<u4').reshape(n,16)
        level=words[:,3];coords=(words[:,:2].astype(np.float32)*scale[level,None]).astype(np.float64)
        uv=cv2.undistortPoints(coords.reshape(-1,1,2),k,distortion,P=k).reshape(-1,2)
        query=np.ascontiguousarray(raw[:,32:64]);pose=poses[item['mapping_timestamp_ns']]
        twc=np.array([[float(pose['twc_%d%d'%(r,c)]) for c in range(4)] for r in range(4)])
        pc=(xyz-twc[:3,3])@twc[:3,:3]
        projected=pc[:,:2]/pc[:,2,None]*[camera['fx'],camera['fy']]+[camera['cx'],camera['cy']]
        metrics={}
        for name,desc,pids in (('exact_representative',reps,ids),('exact_multiview',all_desc,obs_ids),('bounded_native_8views',bounded_desc,bounded_ids)):
            matches=distinct_matches(query,desc,pids)
            error=[float(np.linalg.norm(uv[i]-projected[lookup[pid]])) if pc[lookup[pid],2]>0 else float('inf') for i,pid,d in matches]
            metrics[name]=dict(matches=len(matches),same_run_pose_inliers_3px=sum(e<=3 for e in error),same_run_pose_inliers_6px=sum(e<=6 for e in error))
        native=timed[item['recorded_frame_id']]
        row=dict(recorded_frame=item['recorded_frame_id'],mapping_frame=item['mapping_frame_id'],features=n,
                 actual_native_valid=int(native['pose_valid']),actual_native_matches=int(native['matches']),actual_native_inliers=int(native['inliers']),**metrics)
        results.append(row);print(json.dumps(row),flush=True)
    report=dict(scope=__doc__,status='OFFLINE_SAME_INPUT_DESCRIPTOR_DIAGNOSIS_ONLY',samples=results,physical_receipt_sha256=digest(samples/'RESULT.json'))
    save(output,report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('session','samples','output'):p.add_argument('--'+n,type=Path,required=True)
    analyze(**vars(p.parse_args()))
