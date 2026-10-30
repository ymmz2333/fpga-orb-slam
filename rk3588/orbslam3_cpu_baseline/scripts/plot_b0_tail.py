#!/usr/bin/env python3
"""Render unmodified EuRoC tail frames for qualitative inspection, no SLAM run."""
import csv
import pathlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT=pathlib.Path(__file__).resolve().parent.parent
project=ROOT.parent.parent
timestamps=[int(s) for s in (ROOT/'reports/a2/MH01.txt').read_text().splitlines() if s.strip()]
with (ROOT/'reports/b0/levels1_tail_loss.csv').open() as stream: losses=list(csv.DictReader(stream))
font=next(f.name for f in font_manager.fontManager.ttflist if f.name=='Microsoft YaHei')
plt.rcParams.update({'font.family':font,'axes.unicode_minus':False})
indices=sorted(set([3600,3620,3640,3660,3681]+[int(r['first_frame_index']) for r in losses]))
fig,axes=plt.subplots((len(indices)+2)//3,3,figsize=(14,4*((len(indices)+2)//3)))
for ax,index in zip(axes.flat,indices):
    path=project/'data/euroc/MH_01_easy/mav0/cam0/data'/('%d.png'%timestamps[index])
    ax.imshow(plt.imread(path),cmap='gray',vmin=0,vmax=1)
    ax.set_title('帧 %d｜%.2f s｜%d ns'%(index,(timestamps[index]-timestamps[0])/1e9,timestamps[index]),fontsize=9)
    ax.axis('off')
for ax in list(axes.flat)[len(indices):]: ax.axis('off')
fig.suptitle('MH01 尾段原始图像：B0 只读检查，未经缩放或增强',fontsize=14)
fig.tight_layout(); fig.savefig(ROOT/'reports/b0/tail_frames.png',dpi=160)
print('B0_TAIL_IMAGE_FIGURE_READY')
