"""Batch only UI marker drawing; feature values and 3D geometry are untouched."""
import cv2
import numpy as np

_RING=np.array([(x,y) for y in range(-3,4) for x in range(-3,4) if 4<=x*x+y*y<=10],dtype=np.int64)


def draw_fast(image,features):
    """Screen-only ring stamps; retain feature coordinates/order and palette."""
    if not len(features):return
    values=np.asarray(features,dtype=np.float64)
    if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8 or values.ndim!=2 or values.shape[1]!=4 or not np.isfinite(values).all():raise ValueError('Valid BGR preview and finite features required')
    centers=np.rint(values[:,:2]).astype(np.int64);xy=(centers[:,None,:]+_RING).reshape(-1,2)
    colors=np.where((values[:,3]!=0)[:,None],np.array([135,230,60],np.uint8),np.array([40,188,245],np.uint8));colors=np.repeat(colors,len(_RING),axis=0)
    valid=(xy[:,0]>=0)&(xy[:,0]<image.shape[1])&(xy[:,1]>=0)&(xy[:,1]<image.shape[0]);xy=xy[valid];colors=colors[valid]
    if not len(xy):return
    ids=xy[:,1]*image.shape[1]+xy[:,0]
    # Last marker wins at overlaps, matching the original feature draw order.
    unique,reverse_index=np.unique(ids[::-1],return_index=True)
    image.reshape(-1,3)[unique]=colors[len(colors)-1-reverse_index]

def draw_batch(image,features):
    if not len(features):return
    values=np.asarray(features,dtype=np.float64)
    if values.ndim!=2 or values.shape[1]!=4 or not np.isfinite(values).all():
        raise ValueError('Finite x,y,octave,mapped feature markers required')
    centers=np.ascontiguousarray(np.rint(values[:,:2]),np.float32)
    mapped=values[:,3]!=0
    boundaries=np.r_[0,np.where(mapped[1:]!=mapped[:-1])[0]+1,len(values)]
    # Preserve original order even when differently colored markers overlap.
    if len(boundaries)>17:
        for x,y,octave,flag in features:
            cv2.circle(image,(round(x),round(y)),3,(135,230,60) if flag else (40,188,245),1,cv2.LINE_AA)
        return
    for lo,hi in zip(boundaries[:-1],boundaries[1:]):
        keys=cv2.KeyPoint_convert(centers[lo:hi],size=6)
        cv2.drawKeypoints(image,keys,image,(135,230,60) if mapped[lo] else (40,188,245),cv2.DRAW_MATCHES_FLAGS_DRAW_OVER_OUTIMG)
