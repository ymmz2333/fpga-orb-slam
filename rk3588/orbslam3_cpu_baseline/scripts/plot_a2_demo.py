#!/usr/bin/env python3
"""300-dpi scientific figures derived read-only from the five A2 raw runs."""
import argparse
import csv
import decimal
import hashlib
import json
import pathlib
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib import font_manager
import numpy as np
from analyze_a2 import category
from evaluate_a2 import associate, umeyama

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--batch', default='MH01_600x350_passive_01')
args = parser.parse_args()
raw = ROOT/'reports/a2'/args.batch/'raw'
out = ROOT/'demo/figures'
out.mkdir(parents=True, exist_ok=True)
fonts = {font.name for font in font_manager.fontManager.ttflist}
font = next((name for name in ('Microsoft YaHei','SimHei','Noto Sans CJK SC') if name in fonts), None)
if font is None:
    raise RuntimeError('A Chinese font must be installed; do not generate missing-glyph figures')
plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'font.size':11,
                     'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':120})
inputs = {}
def read(path):
    inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.read_text(encoding='utf-8')

reference_path = raw/'groundtruth_cam0.tum'
reference = np.loadtxt(read(reference_path).splitlines())
runs = []
for folder in sorted(raw.glob('attempt_*')):
    states = list(csv.DictReader(read(folder/'TrackingStates.csv').splitlines()))
    times = np.asarray(list(csv.reader(read(folder/'TrackingTimeStats.txt').splitlines()[1:])), dtype=float)
    if len(states) != len(times) or len(times) != 3682:
        raise RuntimeError('Timing/state row alignment failed')
    normal = np.array([category(int(s['state_before']),int(s['state_after']))=='normal' for s in states])
    poses = []
    for line in read(folder/'f_MH01.txt').splitlines():
        values = line.split()
        if values and not values[0].startswith('#'):
            poses.append([float(decimal.Decimal(values[0])/decimal.Decimal(10**9))]+list(map(float,values[1:])))
    estimate = np.asarray(poses)
    ri, ei = associate(reference[:,0],estimate[:,0])
    transform, errors = umeyama(reference[ri,1:4],estimate[ei,1:4])
    rmse = float(np.sqrt(np.mean(errors**2)))
    existing = json.loads(read(folder/'ate.json'))
    if not np.isclose(rmse,existing['ate_rmse_m'],rtol=1e-7,atol=1e-9):
        raise RuntimeError('Raw trajectory recomputation disagrees with accepted A2 ATE')
    aligned = transform['scale']*(np.asarray(transform['rotation']) @ estimate[ei,1:4].T).T+transform['translation']
    runs.append(dict(name=folder.name,rmse=rmse,errors=errors,aligned=aligned,reference=reference[ri,1:4],
                     timing=times,normal=normal,states=states,
                     ratio_sums=float(times[normal,2].sum()/times[normal,8].sum()),
                     ratio_frame_median=float(np.median(times[normal,2]/times[normal,8]))))
if len(runs)!=5:
    raise RuntimeError('Exactly five A2 raw runs are required')
chosen = sorted(runs,key=lambda run:run['rmse'])[2]
subtitle = 'A2：600×350，官方 YAML 非等比缩放'
def save(fig,name):
    fig.savefig(out/name,dpi=300,bbox_inches='tight',facecolor='white')
    plt.close(fig)

fig,ax = plt.subplots(figsize=(10,6.5))
ax.plot(chosen['reference'][:,0],chosen['reference'][:,1],color='#252b35',lw=1.8,label='相机真值')
points = chosen['aligned'][:,:2]
segments = np.stack((points[:-1],points[1:]),axis=1)
collection = LineCollection(segments,cmap='viridis',linewidths=2.4)
collection.set_array((chosen['errors'][:-1]+chosen['errors'][1:])/2*100)
ax.add_collection(collection)
ax.scatter(*points[0],s=65,color='#e66d27',marker='o',label='估计轨迹起点',zorder=4)
ax.autoscale_view(); ax.set_aspect('equal',adjustable='datalim')
bar = fig.colorbar(collection,ax=ax,pad=.02); bar.set_label('APE 位置误差（cm）')
ax.set(xlabel='X（m）',ylabel='Y（m）',title='轨迹俯视图：Sim3 对齐\n%s｜%s，ATE RMSE %.2f cm' % (subtitle,chosen['name'],chosen['rmse']*100))
ax.grid(alpha=.2); ax.legend(loc='best')
save(fig,'01_trajectory_xy.png')

t = np.array([float(s['timestamp_s']) for s in chosen['states']]); t -= t[0]
fig,axes = plt.subplots(2,1,figsize=(11,7.5),sharex=True,gridspec_kw={'height_ratios':[1,1.6]})
for ax in axes:
    ax.plot(t,chosen['timing'][:,8],lw=.8,color='#27689a',label='Total（含图像缩放）')
    ax.plot(t,chosen['timing'][:,2],lw=.8,color='#e18b2f',label='ORB 提取')
    ax.axhline(33,color='#677079',ls='--',lw=1,label='33 ms')
    ax.axhline(50,color='#b84b4b',ls='--',lw=1,label='50 ms')
    ax.set_ylabel('每帧耗时（ms）'); ax.grid(alpha=.2)
axes[0].set_ylim(0,max(chosen['timing'][:,8])*1.08)
axes[1].set_ylim(0,70); axes[1].set_xlabel('序列时间（s）')
axes[0].set_title('逐帧耗时：%s｜%s\n上：完整范围（含初始化）；下：0–70 ms 放大，超过范围的峰值见上图' % (subtitle,chosen['name']))
axes[0].legend(ncol=4,loc='upper right')
save(fig,'02_frame_timing.png')

ratio = statistics.median(r['ratio_sums'] for r in runs)*100
frame_ratio = statistics.median(r['ratio_frame_median'] for r in runs)*100
fig,ax = plt.subplots(figsize=(10,3.8))
ax.barh([0],[ratio],color='#e18b2f',height=.45,label='ORB 提取')
ax.barh([0],[100-ratio],left=[ratio],color='#69859b',height=.45,label='其余跟踪耗时（含图像缩放）')
ax.text(ratio/2,0,'ORB 提取\n%.2f%%'%ratio,ha='center',va='center',fontsize=15)
ax.text(ratio+(100-ratio)/2,0,'其余部分\n%.2f%%'%(100-ratio),ha='center',va='center',fontsize=15,color='white')
ax.set(xlim=(0,100),yticks=[],xlabel='跟踪线程 Total 的耗时占比（%）',
       title='模块耗时构成｜%s｜五次中位数' % subtitle)
ax.text(.5,-.32,'口径：每次仅正常帧 sum(ORB)/sum(Total)，再取五次中位数\n另一口径：逐帧比值的中位数，再取五次中位数 = %.2f%%'%frame_ratio,
        transform=ax.transAxes,ha='center',va='top',fontsize=10)
save(fig,'03_orb_share.png')

fig,ax = plt.subplots(figsize=(8,5))
values = np.array([r['rmse']*100 for r in runs]); median = float(np.median(values))
ax.scatter(np.arange(1,6),values,s=100,color='#27689a',zorder=3,label='每次运行')
ax.axhline(median,color='#e18b2f',ls='--',label='中位数 %.2f cm'%median)
for index,v in enumerate(values,1):
    ax.annotate('%.2f'%v,(index,v),xytext=(0,9),textcoords='offset points',ha='center')
ax.set(xlim=(.6,5.4),ylim=(0,max(values)*1.2),xticks=np.arange(1,6),xlabel='运行序号（次）',ylabel='ATE RMSE（cm）',
       title='五次 ATE 分布（Sim3）\n'+subtitle)
ax.legend(); ax.grid(alpha=.2)
save(fig,'04_ate_runs.png')

with (out/'figure_data.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream); writer.writerow(['run','tracking_width','tracking_height','resize_policy','ate_rmse_m','orb_ratio_sums','orb_ratio_frame_median'])
    writer.writerows((r['name'],600,350,'official nonuniform resize',r['rmse'],r['ratio_sums'],r['ratio_frame_median']) for r in runs)
manifest=dict(purpose='D2 visualization of accepted A2 data; no new SLAM run',selected_run=chosen['name'],
              tracking_resolution='600x350',resize_policy='official nonuniform resize',dpi=300,font=font,
              selected_ate_rmse_m=chosen['rmse'],raw_inputs_sha256=inputs,
              figures_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.png')})
(out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print('D2_FIGURES_PASS selected=%s figures=4 dpi=300 font=%s'% (chosen['name'],font))
