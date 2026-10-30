"""Calibrate the actual camera from a checkerboard video; never substitute borrowed K for observations."""
import argparse,json,pathlib
import cv2,numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
def calibrate(object_points,image_points,size,initial=None):
    if len(image_points)<10: raise ValueError('Need at least ten detected board views with varied poses')
    flags=cv2.CALIB_USE_INTRINSIC_GUESS if initial is not None else 0
    rms,K,D,rot,trans=cv2.calibrateCamera(object_points,image_points,size,initial,None,flags=flags)
    errors=[]
    for obj,img,r,t in zip(object_points,image_points,rot,trans):
        projected,_=cv2.projectPoints(obj,r,t,K,D)
        errors.append(float(np.sqrt(np.mean(np.sum((projected.reshape(-1,2)-img.reshape(-1,2))**2,axis=1)))))
    return rms,K,D,errors
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True); p.add_argument('--corners',nargs=2,type=int,required=True,metavar=('COLS','ROWS'))
    p.add_argument('--square-size-m',type=float,required=True); p.add_argument('--output',type=pathlib.Path,required=True)
    p.add_argument('--sample-every',type=int,default=15); p.add_argument('--max-views',type=int,default=100)
    p.add_argument('--slam-fps',type=int,default=30,help='Integer nominal rate required by ORB-SLAM3 v1.0; Tello default 30')
    p.add_argument('--initial-yaml',type=pathlib.Path); a=p.parse_args()
    if min(a.corners)<2 or a.square_size_m<=0 or a.sample_every<1 or a.slam_fps<1: raise ValueError('Invalid board dimensions/sampling/frame rate')
    if a.output.exists(): raise ValueError('Refusing existing calibration output')
    a.output.mkdir(parents=True); obj=np.zeros((a.corners[0]*a.corners[1],3),np.float32)
    obj[:,:2]=np.mgrid[0:a.corners[0],0:a.corners[1]].T.reshape(-1,2)*a.square_size_m
    capture=cv2.VideoCapture(a.video); fps=capture.get(cv2.CAP_PROP_FPS)
    images=[]; objects=[]; indexes=[]; size=None; index=0
    while len(images)<a.max_views:
        ok,frame=capture.read()
        if not ok: break
        current=(frame.shape[1],frame.shape[0])
        if size is not None and current!=size: raise ValueError('Video resolution changed')
        size=current
        if index%a.sample_every==0:
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            found,corners=cv2.findChessboardCorners(gray,tuple(a.corners),cv2.CALIB_CB_ADAPTIVE_THRESH|cv2.CALIB_CB_NORMALIZE_IMAGE)
            if found:
                corners=cv2.cornerSubPix(gray,corners,(11,11),(-1,-1),(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,30,.001))
                images.append(corners); objects.append(obj.copy()); indexes.append(index)
                cv2.drawChessboardCorners(frame,tuple(a.corners),corners,found)
                cv2.imwrite(str(a.output/('view_%06d.png'%index)),frame)
        index+=1
    capture.release(); initial=None
    if a.initial_yaml:
        f=cv2.FileStorage(str(a.initial_yaml),cv2.FILE_STORAGE_READ)
        if (int(f.getNode('Camera.width').real()),int(f.getNode('Camera.height').real()))!=size: raise ValueError('Initial K resolution mismatch')
        initial=np.array([[f.getNode('Camera1.fx').real(),0,f.getNode('Camera1.cx').real()],
                          [0,f.getNode('Camera1.fy').real(),f.getNode('Camera1.cy').real()],[0,0,1]],dtype=np.float64); f.release()
    try: rms,K,D,errors=calibrate(objects,images,size,initial)
    except Exception as e:
        (a.output/'failure.json').write_text(json.dumps(dict(status='未完成',reason=str(e),detected_views=len(images)),ensure_ascii=False),encoding='utf-8'); raise
    result=dict(status='CALIBRATED_FROM_OBSERVATIONS',reprojection_rmse_px=float(rms),K=K.tolist(),distortion=D.ravel().tolist(),
        width=size[0],height=size[1],inner_corners=a.corners,square_size_m=a.square_size_m,frame_indexes=indexes,
        video_container_fps=fps,slam_nominal_fps=a.slam_fps,
        per_view_rmse_px=errors,pose_diversity='Inspect retained corner overlays; no automatic quality threshold assumed')
    (a.output/'calibration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    template=(ROOT/'configs/c/tello_oafd_960x720_provisional.yaml').read_text(encoding='utf-8')
    import re
    values={'Camera1.fx':K[0,0],'Camera1.fy':K[1,1],'Camera1.cx':K[0,2],'Camera1.cy':K[1,2],
            'Camera.width':size[0],'Camera.height':size[1],'Camera.fps':a.slam_fps}
    values.update(dict(zip(['Camera1.k1','Camera1.k2','Camera1.p1','Camera1.p2'],D.ravel()[:4])))
    template='\n'.join(s for s in template.splitlines() if not s.startswith('#'))
    for key,v in values.items(): template=re.sub(r'^'+re.escape(key)+r':.*$',key+': '+str(v),template,flags=re.M)
    template+='\nCamera1.k3: '+str(D.ravel()[4])+'\n'
    template=template.replace('%YAML:1.0','%YAML:1.0\n# Calibrated from own checkerboard observations; see calibration.json',1)
    (a.output/'camera_calibrated.yaml').write_text(template,encoding='utf-8',newline='\n')
    print('CALIBRATION_RESULT views=%d reprojection_RMSE=%.6fpx'%(len(images),rms))
if __name__=='__main__': main()
