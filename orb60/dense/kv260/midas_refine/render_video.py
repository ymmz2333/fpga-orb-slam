"""Render measured FP32/QAT depth and colored point-cloud comparisons."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import cv2
import numpy as np
from ..common import save,digest,read_tensor
from ...ply import read_ply,write_ply
from ..evaluate import clouds


def label(canvas,text,xy,size=.6,color=(35,35,35)):
    cv2.putText(canvas,text,xy,cv2.FONT_HERSHEY_SIMPLEX,size,color,1,cv2.LINE_AA)


def heat(value,low,high):
    intensity=np.clip((value-low)/max(high-low,1e-9),0,1)
    return cv2.applyColorMap(np.rint(intensity*255).astype(np.uint8),cv2.COLORMAP_INFERNO)


def video(folder):
    report=json.loads((folder/'status.json').read_text())
    if report['status']!='VIDEO_DEPTH_COMPLETE':raise ValueError('Inference not complete')
    rows=report['samples'];values=np.concatenate([read_tensor(folder/'float_depth'/(r['id']+'.f32'),(256,256)).ravel() for r in rows])
    low,high=np.quantile(values,[.01,.99]);del values
    width,height=960,840;raw=folder/'comparison_mjpeg.avi'
    writer=cv2.VideoWriter(str(raw),cv2.VideoWriter_fourcc(*'MJPG'),report['playback_fps'],(width,height))
    if not writer.isOpened():raise RuntimeError('Video writer unavailable')
    worst=max(rows,key=lambda r:r['normalized_rmse']);covers={worst['id']:'worst_frame.png',rows[len(rows)//2]['id']:'preview.png'}
    try:
        for r in rows:
            name=r['id'];rgb=cv2.imread(str(folder/'rgb'/(name+'.png')))
            if rgb is None or digest(folder/'rgb'/(name+'.png'))!=r['rgb_sha256']:raise ValueError('Damaged video RGB')
            reference=read_tensor(folder/'float_depth'/(name+'.f32'),(256,256));candidate=read_tensor(folder/'qat_depth'/(name+'.f32'),(256,256))
            span=float(np.quantile(reference,.95)-np.quantile(reference,.05))
            error=np.abs(candidate-reference)/max(span,1e-9)
            canvas=np.full((height,width,3),248,np.uint8)
            panels=[rgb,heat(reference,low,high),heat(candidate,low,high),heat(error,0,.30)]
            titles=['Recorded RGB','Original MiDaS FP32','Fine-tuned MiDaS INT8 reference','Difference from FP32 (0 - 30%+)']
            for i,(panel,title) in enumerate(zip(panels,titles)):
                x=(i%2)*480;y=(i//2)*394
                label(canvas,title,(x+12,y+25),.58)
                canvas[y+34:y+394,x:x+480]=cv2.resize(panel,(480,360),interpolation=cv2.INTER_LINEAR)
            label(canvas,'Frame %d | source %.2f s | NRMSE %.1f%% | Spearman %.3f'%(r['source_frame_index'],r['source_seconds'],100*r['normalized_rmse'],r['spearman']),(12,809),.58)
            label(canvas,'Shared depth color scale: bright = near | Sampled replay, not KV260 execution',(12,831),.51)
            writer.write(canvas)
            if name in covers:cv2.imwrite(str(folder/covers[name]),canvas)
    finally:writer.release()
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('FFmpeg is required for browser-compatible H264')
    target=folder/'midas_qat_video_comparison.mp4';temp=folder/'comparison.part.mp4'
    with (folder/'encode.log').open('w') as log:
        subprocess.run([ffmpeg,'-y','-i',str(raw),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(temp)],stdout=log,stderr=log,check=True)
    temp.replace(target)
    # Independently decode the encoded video and verify every frame.
    cap=cv2.VideoCapture(str(target));count=0
    while True:
        ok,frame=cap.read()
        if not ok:break
        if frame.shape[:2]!=(height,width):raise ValueError('Encoded video dimensions mismatch')
        count+=1
    cap.release()
    if count!=len(rows):raise ValueError('Encoded video frame count mismatch')
    metrics={'status':'VIDEO_RENDER_PASS','frames':count,'playback_fps':report['playback_fps'],'duration_seconds':count/report['playback_fps'],
             'shared_depth_color_range':[float(low),float(high)],'per_frame_output_alignment':'none',
             'mean_nrmse':float(np.mean([r['normalized_rmse'] for r in rows])),'worst_nrmse':worst['normalized_rmse'],
             'minimum_spearman':min(r['spearman'] for r in rows),'video_sha256':digest(target),'hardware_verified':False}
    save(folder/'video_summary.json',metrics);return metrics


def cloud(folder,root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reference=root/'orb60/build/kv260/cloud_reference/map_0';candidate=folder/'cloud/map_0'
    a=json.loads((reference/'result.json').read_text());b=json.loads((candidate/'result.json').read_text())
    xyz,rgb=read_ply(candidate/'dense.ply');ratio=b['reference_median_depth_raw']/a['reference_median_depth_raw']
    # Undo only the recorded export unit difference; do not estimate a scale/pose alignment.
    write_ply(candidate/'dense_comparable.ply',xyz*ratio,rgb)
    metrics=clouds(reference/'dense.ply',candidate/'dense_comparable.ply')
    metrics.update(reference_valid_keyframes=a['valid_depth_keyframes'],candidate_valid_keyframes=b['valid_depth_keyframes'],
                   reference_fused_keyframes=a['fused_keyframes'],candidate_fused_keyframes=b['fused_keyframes'],
                   export_unit_conversion=ratio,alignment='recorded export unit conversion only; no fitted scale or pose',
                   hardware_verified=False,comparison='against floating reference, not physical ground truth')
    save(folder/'cloud_comparison.json',metrics)
    points_a,colors_a=read_ply(reference/'dense.ply');points_b,colors_b=read_ply(candidate/'dense_comparable.ply')
    joined=np.vstack((points_a,points_b));limits=np.percentile(np.c_[joined[:,0],joined[:,2],-joined[:,1]],[.5,99.5],axis=0)
    fig=plt.figure(figsize=(12,6),facecolor='#f6f7f9')
    for i,(points,colors,title) in enumerate([(points_a,colors_a,'Original MiDaS FP32'),(points_b,colors_b,'Fine-tuned INT8 reference')]):
        idx=np.linspace(0,len(points)-1,min(len(points),90000)).astype(int);points=points[idx];colors=colors[idx]
        ax=fig.add_subplot(1,2,i+1,projection='3d');ax.set_facecolor('#f6f7f9')
        ax.scatter(points[:,0],points[:,2],-points[:,1],c=colors/255.,s=.32,depthshade=False,rasterized=True)
        ax.view_init(elev=12,azim=-65);ax.set_title(title,fontsize=13)
        for setter,lim in zip([ax.set_xlim,ax.set_ylim,ax.set_zlim],limits.T):setter(lim)
        ax.set_box_aspect(np.maximum(limits[1]-limits[0],.01));ax.set_xlabel('x');ax.set_ylabel('z');ax.set_zlabel('-y')
        ax.tick_params(labelsize=8)
    fig.suptitle('Same saved poses, filtering and fusion settings',fontsize=16)
    fig.text(.5,.035,'%s / %s RGB points | relative scale | CPU reference replay, not board execution'%(len(points_a),len(points_b)),ha='center',fontsize=10,color='#4b5563')
    fig.subplots_adjust(left=.01,right=.99,bottom=.09,top=.88,wspace=.02);fig.savefig(folder/'pointcloud_comparison.png',dpi=180);plt.close(fig)
    return metrics


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['video','cloud','all'],default='all');a=p.parse_args()
    cv2.setNumThreads(2);root=Path(__file__).resolve().parents[4];folder=root/'orb60/build/kv260/midas_refine/video_test'
    if a.stage in ['video','all']:print(json.dumps(video(folder)))
    if a.stage in ['cloud','all']:print(json.dumps(cloud(folder,root)))

if __name__=='__main__':main()
