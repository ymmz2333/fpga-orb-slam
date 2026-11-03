"""Render actual RGB point data; no invented surfaces or generated imagery."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ..ply import read_ply


def main():
    p=argparse.ArgumentParser();p.add_argument('--cloud',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--family',default='MiDaS');p.add_argument('--backend',default='reference',choices=['reference','quantized-reference']);a=p.parse_args()
    xyz,rgb=read_ply(a.cloud)
    # Uniformly retain up to 90k actual points, identical sample in both views.
    idx=np.linspace(0,len(xyz)-1,min(len(xyz),90000)).astype(int);points=xyz[idx];colors=rgb[idx]/255.
    fig=plt.figure(figsize=(12,6),facecolor='#f6f7f9')
    for i,(azim,title) in enumerate([(-65,'Oblique view'),(20,'Side view')]):
        ax=fig.add_subplot(1,2,i+1,projection='3d');ax.set_facecolor('#f6f7f9')
        ax.scatter(points[:,0],points[:,2],-points[:,1],c=colors,s=.32,depthshade=False,rasterized=True)
        ax.view_init(elev=12,azim=azim);ax.set_title(title,fontsize=12)
        limits=np.percentile(np.c_[points[:,0],points[:,2],-points[:,1]],[.5,99.5],axis=0)
        for fn,lim in zip([ax.set_xlim,ax.set_ylim,ax.set_zlim],limits.T):fn(lim)
        ax.set_xlabel('x');ax.set_ylabel('z');ax.set_zlabel('-y');ax.set_box_aspect(np.maximum(limits[1]-limits[0],.01))
        ax.tick_params(labelsize=8)
    fig.suptitle(a.family+' | '+a.backend+' | host replay',fontsize=16)
    fig.text(.5,.035,f'{len(xyz):,} RGB points | saved poses, relative scale | DPU / board not verified',ha='center',fontsize=10,color='#4b5563')
    fig.subplots_adjust(left=.01,right=.99,bottom=.09,top=.88,wspace=.02)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=180);plt.close(fig)

if __name__=='__main__':main()
