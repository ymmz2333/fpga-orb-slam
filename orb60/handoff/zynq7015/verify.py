"""Offline evidence checks. No board, RK3588, CPU ORB or SLAM installation needed."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import struct
import time
import zlib
import cv2
import numpy as np
from common import Features,feature_points,load,rows,save,sha,pose_error,pose_from_row

def require(condition,message):
    if not condition:raise ValueError(message)

def checksums(root):
    count=0
    for line in (root/'SHA256SUMS').read_text(encoding='ascii').splitlines():
        expected,name=line.split('  ',1);path=(root/name).resolve()
        require(path.is_relative_to(root.resolve()),'Unsafe checksum path')
        require(sha(path)==expected,'SHA256 mismatch: '+name);count+=1
    require(count>100,'Incomplete bundle checksum inventory')
    return count

def golden(root):
    folder=root/'golden';features=Features(folder);accept=load(folder/'capture_acceptance.json')
    require(accept['status']=='PASS' and accept['backend']=='physical_fpga','Missing actual FPGA acceptance')
    require(len(features.index)==accept['frames']==2273,'Wrong golden frame count')
    for name in ('features','runtime','headers'):
        require(sha(folder/(name+'.bin'))==accept[name+'_sha256'],'Corrupt capture '+name)
    spec=importlib.util.spec_from_file_location('handoff_wire',root/'reference/ps/client.py')
    require(sha(root/'reference/ps/client.py')==accept['wire_client_sha256'],'Capture decoder source changed')
    wire=importlib.util.module_from_spec(spec);spec.loader.exec_module(wire)
    history={}
    logfile=root/'source_map/slam/output.log'
    require(sha(logfile)==accept['history_sha256'],'Wrong historical feature log')
    for line in logfile.read_text().splitlines():
        if line.startswith('FPGA_ORB_NET '):
            item=dict(part.split('=',1) for part in line.split()[1:] if '=' in part);history[int(item['frame'])]=item
    require(len(history)==2273,'Missing historic frames')
    source=rows(root/'testdata/source_frames.csv')
    require(sha(root/'testdata/source_frames.csv')==accept['source_manifest_sha256'],'Wrong input manifest')
    runtime=(folder/'runtime.bin').read_bytes();headers=(folder/'headers.bin').read_bytes()
    require(len(runtime)==2273*1152 and len(headers)==2273*64,'Missing wire evidence')
    for i,row in enumerate(features.index):
        actual=features.frame(i).tobytes();old=history[i+1];metadata=runtime[i*1152:i*1152+128]
        stats=runtime[i*1152+128:(i+1)*1152];head=headers[i*64:(i+1)*64]
        decoded=wire.decode(head,metadata+actual+stats,i+1,int(row['timestamp_ns']),int(row['role']))
        require(not decoded['simulated'],'Simulated record rejected')
        require(decoded['count']==int(old['count'])==int(row['count']),'Historical count mismatch')
        require(zlib.crc32(actual)==int(old['record_crc'])==int(row['record_crc32']),'Historical record CRC mismatch')
        require(hashlib.sha256(actual).hexdigest()==row['records_sha256'],'Per-frame record hash mismatch')
        require(int(row['source_frame_index'])==int(source[i]['source_frame_index']) and
                int(row['timestamp_ns'])==int(source[i]['timestamp_ns']) and row['png_sha256']==source[i]['sha256'],
                'Input frame identity mismatch')
    require(len(features.data)==accept['records'],'Record total mismatch')
    return features

def decode_inputs(root,features,sample_output=None):
    import av
    video=root/'testdata/video.mp4';accept=load(root/'golden/capture_acceptance.json')
    require(sha(video)==accept['video_sha256'],'Wrong input video')
    requested={int(r['source_frame_index']):r for r in features.index};checked=0;samples={}
    with av.open(str(video)) as container:
        stream=container.streams.video[0]
        for index,frame in enumerate(container.decode(stream)):
            if index not in requested:continue
            row=requested[index];gray=frame.to_ndarray(format='gray')
            require(gray.shape==(720,960),'Unexpected frozen recording geometry')
            require(hashlib.sha256(gray.tobytes()).hexdigest()==row['gray_sha256'],'Decoded pixel mismatch at source frame%d'%index)
            pts=float(frame.pts*frame.time_base)
            require(abs(pts-float(row['mp4_pts_s']))<1e-6,'Video PTS mismatch')
            checked+=1
            if int(row['frame_index']) in (200,1000,1800):samples[int(row['frame_index'])]=gray.copy()
    require(checked==2273,'Missing decoded inputs')
    if sample_output is not None:
        from render import feature_overlay,map_view
        sample_output.mkdir(parents=True,exist_ok=True)
        for index,gray in samples.items():
            require(cv2.imwrite(str(sample_output/('features_%04d.png'%index)),feature_overlay(gray,features.frame(index))),'Preview write failed')
        xyz=np.fromfile(root/'map/points.bin',dtype='<f4').reshape(-1,3)
        trajectory=rows(root/'localization_reference/trajectory.csv')
        poses=[pose_from_row(r) for r in trajectory if int(r['pose_valid'])]
        positions=[pose_from_row(r)[:3,3] if int(r['pose_valid']) else [np.nan]*3 for r in trajectory]
        require(cv2.imwrite(str(sample_output/'raw_map_and_trajectory.png'),map_view(xyz,positions,poses[-1])),'Map preview write failed')
    return checked

def map_data(root,features):
    folder=root/'map';meta=load(folder/'map.json');obs=rows(folder/'observations.csv');points=rows(folder/'points.csv')
    source=rows(root/'source_map/slam/keyframes/map_0/observations.csv')
    require((meta['points'],meta['keyframes'],len(obs))==(2547,130,18980),'Unexpected frozen map dimensions')
    require(meta['world_scale_applied']==1 and meta['reference_median_depth']>0,'World scale changed')
    xyz=np.fromfile(folder/'points.bin',dtype='<f4').reshape(-1,3);ids=np.fromfile(folder/'point_ids.bin',dtype='<u8')
    desc=np.fromfile(folder/'observation_descriptors.bin',dtype=np.uint8).reshape(-1,32)
    rep=np.fromfile(folder/'representative_descriptors.bin',dtype=np.uint8).reshape(-1,32)
    require(len(xyz)==len(ids)==len(rep)==2547 and len(desc)==18980,'Wrong binary map lengths')
    require(len(set(ids.tolist()))==len(ids) and np.isfinite(xyz).all(),'Invalid map points')
    for i,(row,old) in enumerate(zip(obs,source)):
        require(all(row[k]==v for k,v in old.items()),'Original observation changed')
        record=features.frame(int(row['frame_index']))[int(row['record_index'])]
        require(np.array_equal(record['descriptor'],desc[i]),'Observation descriptor association failed')
        uv=feature_points(np.array([record]))[0]
        require(np.max(np.abs(uv-[float(row['raw_u']),float(row['raw_v'])]))<=.002,'Observation coordinate association failed')
    point_lookup={int(pid):p for pid,p in zip(ids,xyz)}
    maximum_projection_error=0.;maximum_undistortion_error=0.
    for key in rows(folder/'keyframes.csv'):
        subset=[r for r in obs if r['keyframe_id']==key['keyframe_id']]
        world=np.array([point_lookup[int(r['point_id'])] for r in subset],np.float64)
        twc=pose_from_row(key);camera=(world-twc[:3,3])@twc[:3,:3]
        require(np.all(camera[:,2]>0),'Map point behind observing keyframe')
        k=np.array([[float(key['fx']),0,float(key['cx'])],[0,float(key['fy']),float(key['cy'])],[0,0,1]])
        projected=camera[:,:2]/camera[:,2,None]*[k[0,0],k[1,1]]+[k[0,2],k[1,2]]
        observed=np.array([[float(r['u']),float(r['v'])] for r in subset])
        maximum_projection_error=max(maximum_projection_error,float(np.linalg.norm(projected-observed,axis=1).max()))
        raw=np.array([[float(r['raw_u']),float(r['raw_v'])] for r in subset])
        undistorted=cv2.undistortPoints(raw.reshape(-1,1,2),k,np.array([float(key['d'+str(i)]) for i in range(5)]),P=k).reshape(-1,2)
        maximum_undistortion_error=max(maximum_undistortion_error,float(np.linalg.norm(undistorted-observed,axis=1).max()))
    require(maximum_projection_error<=3.001,'Raw world/pose reprojection failed')
    require(maximum_undistortion_error<=.003,'Raw/undistorted keypoint mismatch')
    for i,row in enumerate(points):
        require(int(row['point_id'])==int(ids[i]),'Point ID order changed')
        require(np.array_equal(np.asarray([float(row[c]) for c in ('x','y','z')],np.float32),xyz[i]),'Point position changed')
        require(np.array_equal(rep[i],desc[int(row['representative_observation_row'])]),'Representative is not an actual observation')
    reference=rows(folder/'slam_reference.csv');states=rows(root/'source_map/slam/TrackingStates.csv')
    require(len(reference)==len(features.index)==len(states),'Missing canonical trajectory frames')
    for i,row in enumerate(reference):
        require(int(row['frame_index'])==i and int(row['timestamp_ns'])==int(features.index[i]['timestamp_ns']),'Trajectory frame identity error')
        require(int(row['tracking_state'])==int(states[i]['state_after']),'Tracking state changed')
        if int(row['pose_valid']):
            require(int(row['tracking_state'])==2 and np.isfinite(pose_from_row(row)).all(),'Invalid tracking pose marked valid')
        else:require(all(row['twc_%d%d'%(r,c)]=='' for r in range(4) for c in range(4)),'Lost pose was fabricated')
    return dict(points=len(xyz),observations=len(obs),original_slam_valid=sum(int(r['pose_valid']) for r in reference),
                maximum_reprojection_px=maximum_projection_error,maximum_undistortion_error_px=maximum_undistortion_error)

def solver_cases(root,output):
    folder=root/'localization_reference/pnp_cases';depth=load(root/'map/map.json')['reference_median_depth'];errors=[]
    cv2.setNumThreads(1)
    config=load(root/'localization_reference/configuration.json')
    require(config['implementation_sha256']==sha(root/'tools/localize.py'),'Frozen localizer implementation changed')
    require(config['golden_features_sha256']==sha(root/'golden/features.bin') and config['map_sha256']==sha(root/'map/map.json'),'Wrong localizer input binding')
    for entry in load(folder/'index.json'):
        case=load(folder/(entry['name']+'.json'));data=rows(folder/(entry['name']+'.csv'))
        xyz=np.array([[float(r[c]) for c in ('x','y','z')] for r in data]);uv=np.array([[float(r[c]) for c in ('u','v')] for r in data])
        rvec=np.array(case['initial_rvec'],np.float64);tvec=np.array(case['initial_tvec'],np.float64)
        ok,rvec,tvec=cv2.solvePnP(xyz,uv,np.array(case['k']),None,rvec,tvec,True,flags=cv2.SOLVEPNP_ITERATIVE)
        require(ok,'Fixed-inlier PnP failed');rotation,_=cv2.Rodrigues(rvec);twc=np.eye(4)
        twc[:3,:3]=rotation.T;twc[:3,3]=-rotation.T@tvec.ravel()
        translation,angle=pose_error(np.array(case['twc']),twc,depth)
        require(translation<=.001 and angle<=.1,'Fixed-inlier PnP threshold failed')
        errors.append(dict(case=entry['name'],position_error_relative=translation,rotation_error_degrees=angle))
    require(len(errors)==20,'Expected20 frozen fixed-inlier cases')
    save(output/'fixed_pnp_check.json',dict(status='PASS',opencv=cv2.__version__,cases=errors,
        scope='Frozen same-inlier solver regression; cross-version C++ evidence is supplied separately'))
    return len(errors)

def candidate_features(features,candidate,output):
    actual=Features(candidate);require(len(actual.index)==len(features.index),'Missing candidate feature frames')
    for i,(ref,row) in enumerate(zip(features.index,actual.index)):
        require(all(int(ref[k])==int(row[k]) for k in ('frame_index','source_frame_index','timestamp_ns','count')),'Candidate feature identity/count mismatch')
        require(features.frame(i).tobytes()==actual.frame(i).tobytes(),'Candidate feature byte mismatch at frame%d'%i)
    save(output/'feature_comparison.json',dict(status='PASS',frames=len(actual.index),records=len(actual.data),comparison='All64 record bytes in original order'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--candidate',type=Path);p.add_argument('--candidate-features',type=Path)
    p.add_argument('--skip-video',action='store_true',help='Integrity-only quick check; does not claim decoded-input validation')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);start=time.perf_counter();report=dict(status='FAIL')
    try:
        report['files_checked']=checksums(a.bundle)
        features=golden(a.bundle);report['hardware_frames']=len(features.index)
        report['map']=map_data(a.bundle,features);report['fixed_inlier_cases']=solver_cases(a.bundle,a.output)
        report['decoded_input_frames']=0 if a.skip_video else decode_inputs(a.bundle,features,a.output/'previews')
        if a.candidate_features:candidate_features(features,a.candidate_features,a.output)
        if a.candidate:
            from compare import compare
            result=compare(a.bundle/'localization_reference/trajectory.csv',a.candidate,a.bundle/'map',a.output/'candidate')
            require(result['status']=='PASS','Candidate full localization acceptance failed')
            report['candidate_localization']='PASS'
        report.update(status='PASS',candidate_tested=bool(a.candidate or a.candidate_features),
            claim='Offline regression evidence; no new Zynq PS localization/camera/HDMI acceptance')
    except Exception as error:
        report['error']=str(error);raise
    finally:
        report['seconds']=time.perf_counter()-start;save(a.output/'verification.json',report);print(report,flush=True)

if __name__=='__main__':main()
