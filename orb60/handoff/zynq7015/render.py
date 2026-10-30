"""Software projection reference; outputs an ordinary image/framebuffer, no GPU API."""
import cv2
import numpy as np
from common import feature_points

def feature_overlay(gray,records):
    image=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    for u,v in feature_points(records):cv2.circle(image,(round(float(u)),round(float(v))),2,(0,240,0),1)
    return image

def map_view(xyz,trajectory,twc=None,width=640,height=480):
    image=np.full((height,width,3),(24,20,12),np.uint8)
    xyz=np.asarray(xyz).reshape(-1,3);trajectory=np.asarray(trajectory).reshape(-1,3)
    finite_trajectory=trajectory[np.isfinite(trajectory).all(axis=1)]
    points=np.concatenate([xyz,finite_trajectory]) if len(finite_trajectory) else xyz
    if not len(points):return image
    center=np.median(points,axis=0)
    # Fit the ordinary scene; isolated distant points may be clipped by the view,
    # just as with a normal camera. The map/PLY coordinates are never modified.
    radius=max(float(np.quantile(np.linalg.norm(points-center,axis=1),.99)),.1)
    # Camera axes -> a fixed oblique overview; it changes display only.
    r,_=cv2.Rodrigues(np.array([.7,-.5,.1]));distance=radius*2.5
    def project(data):
        p=(np.asarray(data)-center)@r.T;p[:,2]+=distance
        valid=np.isfinite(p).all(axis=1)&(p[:,2]>.01*radius)
        uv=np.zeros((len(p),2));uv[valid]=p[valid,:2]/p[valid,2,None]*(min(width,height)*1.1)+[width/2,height/2]
        return np.rint(np.clip(uv,-1000000,1000000)).astype(int),valid
    cloud,valid=project(xyz)
    for (x,y),visible in zip(cloud,valid):
        if visible and 0<=x<width and 0<=y<height:image[y,x]=(225,225,225)
    if len(trajectory)>1:
        projected,visible=project(trajectory)
        for i in range(1,len(trajectory)):
            if visible[i-1] and visible[i]:cv2.line(image,tuple(projected[i-1]),tuple(projected[i]),(100,245,170),2)
    if twc is not None:
        at,visible=project(np.asarray(twc)[:3,3][None])
        if visible[0]:cv2.drawMarker(image,tuple(at[0]),(0,220,255),cv2.MARKER_CROSS,12,2)
    return image
