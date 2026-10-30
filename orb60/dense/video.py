"""Lossless video preparation with source PTS, rotation and camera provenance."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import cv2
import numpy as np
from .geometry import letterbox_geometry


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def camera_config(path, width, height, approximate=False):
    if path is None:
        if not approximate:
            raise ValueError('Camera calibration required, or explicitly enable --approximate-camera')
        return dict(k=[[max(width,height),0,(width-1)/2],[0,max(width,height),(height-1)/2],[0,0,1]],
                    distortion=[0.]*5, width=width, height=height, mode='explicit_approximate', sha256=None)
    path = Path(path)
    if path.suffix.lower() == '.json':
        value = json.loads(path.read_text())
        value['sha256'] = digest(path)
        value.setdefault('mode', 'provided_calibration')
        return value
    file = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    def number(name, default=None):
        node = file.getNode(name)
        if node.empty():
            if default is None:
                raise ValueError('Camera configuration missing '+name)
            return default
        return node.real()
    fx, fy, cx, cy = [number('Camera1.'+name) for name in ['fx','fy','cx','cy']]
    value = dict(k=[[fx,0,cx],[0,fy,cy],[0,0,1]],
                 distortion=[number('Camera1.'+name,0) for name in ['k1','k2','p1','p2','k3']],
                 width=int(number('Camera.width')),height=int(number('Camera.height')),
                 mode='provided_calibration',sha256=digest(path))
    file.release()
    if 'provisional' in path.name.lower() or 'NOT a calibration' in path.read_text(encoding='utf-8-sig'):
        value['mode'] = 'explicit_borrowed_provisional_not_calibrated'
    return value


def working_image(bgr, camera, rotation=0):
    h, w = bgr.shape[:2]
    if (camera['width'],camera['height']) != (w,h):
        raise ValueError('Calibration dimensions do not match the unrotated video')
    k = np.asarray(camera['k'], np.float64)
    dist = np.asarray(camera['distortion'], np.float64)
    mask = np.full((h,w),255,np.uint8)
    if np.any(dist):
        mx,my = cv2.initUndistortRectifyMap(k,dist,None,k,(w,h),cv2.CV_32FC1)
        bgr = cv2.remap(bgr,mx,my,cv2.INTER_LINEAR)
        mask = cv2.remap(mask,mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
    angle = int(round(rotation)) % 360
    if angle not in [0,90,180,270]:
        raise ValueError('Only right-angle video rotation is supported')
    fx,fy,cx,cy = k[0,0],k[1,1],k[0,2],k[1,2]
    if angle:
        turns = {90:3,180:2,270:1}[angle]
        bgr,mask = np.rot90(bgr,turns).copy(),np.rot90(mask,turns).copy()
        if angle == 90: fx,fy,cx,cy = fy,fx,h-1-cy,cx
        elif angle == 180: cx,cy = w-1-cx,h-1-cy
        else: fx,fy,cx,cy = fy,fx,cy,w-1-cx
        k = np.array([[fx,0,cx],[0,fy,cy],[0,0,1.]])
    h,w = bgr.shape[:2]
    k,roi,transform = letterbox_geometry(w,h,k)
    x,y,rw,rh = roi
    output = np.zeros((720,960,3),np.uint8)
    valid = np.zeros((720,960),np.uint8)
    output[y:y+rh,x:x+rw] = cv2.resize(bgr,(rw,rh),interpolation=cv2.INTER_AREA)
    valid[y:y+rh,x:x+rw] = cv2.resize(mask,(rw,rh),interpolation=cv2.INTER_NEAREST)
    return output,valid,k,roi,transform


def write_slam_camera(path,k):
    content = ['%YAML:1.0','File.version: "1.0"','Camera.type: "PinHole"']
    # SLAM's typed configuration reader requires real YAML nodes even when an
    # approximate focal length happens to be an integer (e.g. 720.0).
    content += ['Camera1.%s: %s'%(n,repr(float(v))) for n,v in zip(['fx','fy','cx','cy'],[k[0,0],k[1,1],k[0,2],k[1,2]])]
    content += ['Camera1.%s: 0.0'%n for n in ['k1','k2','p1','p2','k3']]
    content += ['Camera.width: 960','Camera.height: 720','Camera.fps: 30','Camera.RGB: 0',
                'ORBextractor.nFeatures: 1000','ORBextractor.scaleFactor: 1.2','ORBextractor.nLevels: 8',
                'ORBextractor.iniThFAST: 20','ORBextractor.minThFAST: 7',
                'Viewer.KeyFrameSize: 0.05','Viewer.KeyFrameLineWidth: 1.0','Viewer.GraphLineWidth: 0.9',
                'Viewer.PointSize: 2.0','Viewer.CameraSize: 0.08','Viewer.CameraLineWidth: 3.0',
                'Viewer.ViewpointX: 0.0','Viewer.ViewpointY: -0.7','Viewer.ViewpointZ: -3.5','Viewer.ViewpointF: 500.0']
    Path(path).write_text('\n'.join(content)+'\n')


def prepare_video(video,camera_path,output,approximate=False):
    output = Path(output)
    image_dir = output/'mav0/cam0/data'
    image_dir.mkdir(parents=True,exist_ok=True)
    probe = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                            'frame=best_effort_timestamp_time:stream','-show_streams','-of','json',str(video)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    metadata=json.loads(probe.stdout)
    frames = metadata['frames']
    if not frames or any('best_effort_timestamp_time' not in f for f in frames):
        raise ValueError('Missing original video timestamps')
    pts = [int(Decimal(f['best_effort_timestamp_time'])*1000000000) for f in frames]
    cap = cv2.VideoCapture(str(video))
    rotation = cap.get(getattr(cv2,'CAP_PROP_ORIENTATION_META',48))
    # OpenCV 4.2 reports zero even for rotated phone videos. FFmpeg's display
    # matrix is counter-clockwise; working_image uses clockwise quarter turns.
    streams=metadata.get('streams',[])
    if streams:
        stream=streams[0]
        matrices=[s['rotation'] for s in stream.get('side_data_list',[]) if 'rotation' in s]
        if matrices:rotation=(-float(matrices[0]))%360
        elif 'rotate' in stream.get('tags',{}):rotation=float(stream['tags']['rotate'])%360
    cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
    rows=[]
    camera=None
    last=-1
    for index,stamp in enumerate(pts):
        ok,bgr = cap.read()
        if not ok:
            raise ValueError('Video decode ended before timestamp manifest; do not invent frame IDs')
        if stamp <= last:
            continue
        if camera is None:
            camera = camera_config(camera_path,bgr.shape[1],bgr.shape[0],approximate)
        image,mask,k,roi,transform = working_image(bgr,camera,rotation)
        timestamp=stamp-pts[0]+1000000000
        relative='mav0/cam0/data/%d.png'%timestamp
        if not cv2.imwrite(str(output/relative),cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)):
            raise IOError('Cannot save working frame')
        rows.append(dict(frame_index=len(rows),timestamp_ns=timestamp,image=relative,
                         source_frame_index=index,mp4_pts_s=str(Decimal(stamp)/1000000000),
                         original_pts_ns=stamp))
        last=stamp
    cap.release()
    with (output/'frames.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    (output/'timestamps.txt').write_text(''.join(str(r['timestamp_ns'])+'\n' for r in rows))
    write_slam_camera(output/'camera.yaml',k)
    cv2.imwrite(str(output/'valid_mask.png'),mask)
    info=dict(video_sha256=digest(video),video=str(Path(video).resolve()),camera=camera,
              rotation_degrees=rotation,roi=list(roi),k=k.tolist(),pixel_transform=transform.tolist(),
              frames=len(rows),mode='rectified_before_slam',source_pts_offset_ns=pts[0])
    (output/'preparation.json').write_text(json.dumps(info,indent=2)+'\n')
    (output/'ffprobe.stderr.txt').write_bytes(probe.stderr)
    return info
