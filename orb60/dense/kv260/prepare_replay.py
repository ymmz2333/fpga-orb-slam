"""Prepare saved keyframes directly from real video; never starts SLAM or NPU."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import cv2
import numpy as np
from .common import checked_id,digest,preprocess,save
from ..geometry import valid_pose
from ..video import working_image


def validate_manifest(manifest):
    maps=set();names=set()
    for m in manifest['maps']:
        if m['map_id'] in maps:raise ValueError('Duplicate map ID')
        maps.add(m['map_id']);previous=-1;keyframes=set()
        for f in m['frames']:
            if not isinstance(f['timestamp_ns'],int) or f['timestamp_ns']<=previous:raise ValueError('Non-integer or unordered timestamp')
            previous=f['timestamp_ns']
            if 'source_frame_index' in f and (not isinstance(f['source_frame_index'],int) or f['source_frame_index']<0):raise ValueError('Invalid source frame index')
            if 'distortion' in f and not np.isfinite(np.asarray(f['distortion'])).all():raise ValueError('Nonfinite camera distortion')
            if f['keyframe_id'] in keyframes or f['map_id']!=m['map_id']:raise ValueError('Keyframe/map identity mismatch')
            keyframes.add(f['keyframe_id'])
            if not valid_pose(np.array(f['twc'])):raise ValueError('Invalid saved pose')
            k=np.array(f['k'])
            if k.shape!=(3,3) or not np.isfinite(k).all() or k[0,0]<=0 or k[1,1]<=0:raise ValueError('Invalid camera matrix')
            name=checked_id(f.get('name','m%d_k%d'%(m['map_id'],f['keyframe_id'])))
            if name in names:raise ValueError('Duplicate frame name')
            names.add(name)
    return manifest


def prepare(saved,video,output,rgb_cache=None,regenerate_inputs=False):
    saved=Path(saved);output=Path(output);video=Path(video)
    manifest=validate_manifest(copy.deepcopy(json.loads((saved/'keyframes.json').read_text())))
    history=json.loads((saved/'state.json').read_text())
    if digest(saved/'keyframes.json')!=history['stages']['select']['artifacts']['keyframes.json']:raise ValueError('Saved keyframe manifest hash mismatch')
    identity={'saved_manifest_sha256':digest(saved/'keyframes.json'),'video_sha256':digest(video),
              'rgb_cache':str(Path(rgb_cache).resolve()) if rgb_cache else None,'regenerate_inputs':regenerate_inputs}
    if identity['video_sha256']!=history['identity']['video_sha256']:raise ValueError('Saved video hash mismatch')
    state=output/'preparation.json'
    if state.exists() and json.loads(state.read_text())['identity']!=identity:raise ValueError('Replay output belongs to different inputs')
    output.mkdir(parents=True,exist_ok=True);(output/'inputs').mkdir(exist_ok=True)
    wanted={};names=[];source_files={};differences=[]
    for m in manifest['maps']:
        mid=m['map_id'];folder=output/('map_%d'%mid)/'keyframes';folder.mkdir(parents=True,exist_ok=True)
        source=saved/'slam/keyframes'/('map_%d'%mid)/'observations.csv'
        relative=str(source.relative_to(saved)).replace('\\','/')
        if digest(source)!=history['stages']['track']['artifacts'][relative]:raise ValueError('Saved sparse observations hash mismatch')
        target=folder.parent/'observations.csv';shutil.copyfile(source,target)
        m['observations']=str(target.relative_to(output)).replace('\\','/');source_files[m['observations']]=digest(target)
        for f in m['frames']:
            if f['selected']:wanted.setdefault(f['source_frame_index'],[]).append(f)
    if not wanted:raise ValueError('No selected saved keyframes')
    cap=cv2.VideoCapture(str(video));prep=manifest.get('preparation')
    if prep:cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
    try:
        for index in range(max(wanted)+1):
            ok,bgr=cap.read()
            if not ok:raise ValueError('Video ended before saved frame %d'%index)
            for f in wanted.get(index,[]):
                name=checked_id(f['name']);k=np.array(f['k']);dist=np.array(f['distortion'])
                if prep:
                    image,mask,actual_k,roi,_=working_image(bgr,prep['camera'],prep['rotation_degrees'])
                    if not np.allclose(actual_k,k,atol=.01):raise ValueError('Camera preparation mismatch')
                else:
                    if bgr.shape[:2]!=(720,960):raise ValueError('Saved untransformed keyframes require 960x720 video')
                    mx,my=cv2.initUndistortRectifyMap(k,dist,None,k,(960,720),cv2.CV_32FC1)
                    image=cv2.remap(bgr,mx,my,cv2.INTER_LINEAR)
                    mask=cv2.remap(np.full((720,960),255,np.uint8),mx,my,cv2.INTER_NEAREST)
                mask=cv2.erode(mask,np.ones((63,63),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
                if rgb_cache:
                    cached=Path(rgb_cache)/f['rgb']
                    expected=history['stages']['select']['artifacts'][f['rgb']]
                    if digest(cached)!=expected:raise ValueError('Cached keyframe RGB hash mismatch')
                    image=cv2.imread(str(cached))
                    if image is None or image.shape!=bgr.shape:raise ValueError('Cached RGB dimensions mismatch')
                    f['saved_rgb_sha256']=expected
                for key,data,suffix in [('rgb',image,'.rgb.png'),('valid_mask',mask,'.valid.png')]:
                    path=output/('map_%d'%f['map_id'])/'keyframes'/(name+suffix)
                    if not cv2.imwrite(str(path),data):raise IOError('Image write failed')
                    f[key]=str(path.relative_to(output)).replace('\\','/');source_files[f[key]]=digest(path)
                x=preprocess(cv2.cvtColor(image,cv2.COLOR_BGR2RGB));path=output/'inputs'/(name+'.input.f32');x.tofile(path)
                if f.get('input_sha256') and digest(path)!=f['input_sha256']:
                    if not regenerate_inputs:raise ValueError('Saved preprocessing hash mismatch: '+name)
                    differences.append({'id':name,'historical':f['input_sha256'],'regenerated':digest(path)})
                    f['historical_input_sha256']=f['input_sha256']
                f['input_sha256']=digest(path);source_files[str(path.relative_to(output)).replace('\\','/')]=digest(path);names.append(name)
                print('PREPARED',name,flush=True)
    finally:cap.release()
    # The worker order is explicit and repeats map order + integer timestamp order.
    names=[f['name'] for m in manifest['maps'] for f in m['frames'] if f['selected']]
    (output/'inputs/names.txt').write_text(''.join(n+'\n' for n in names))
    manifest.update(source='saved keyframes and real video; no SLAM rerun',input_order=names)
    save(output/'keyframes.json',manifest)
    save(state,{'status':'REPLAY_INPUTS_PASS','identity':identity,'selected':len(names),'files':source_files,
                'historical_tensor_reproduction':'NOT_REPRODUCED' if differences else 'MATCH',
                'input_differences':differences,'note':'Verified saved RGB is re-normalized with the current frozen RGB/NCHW contract; historical RK tensors are not claimed reproduced.'})
    return manifest


def main():
    p=argparse.ArgumentParser()
    for key in ['saved','video','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--rgb-cache',type=Path);p.add_argument('--regenerate-inputs',action='store_true')
    a=p.parse_args();prepare(**vars(a))

if __name__=='__main__':main()
