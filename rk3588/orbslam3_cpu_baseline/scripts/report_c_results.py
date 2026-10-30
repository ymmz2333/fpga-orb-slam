"""Reproduce the preliminary C2 report and figures from preserved results/raw logs."""
import argparse,collections,hashlib,json,os,pathlib,re,statistics
import numpy as np
from analyze_c import read,write
from finish_c import trajectory
from evaluate_a2 import umeyama

def label(clip):
    t=re.search(r'T(\d{2})(\d{2})(\d{2})',clip)
    return ('飞行' if clip.startswith('flight') else '手持')+' '+':'.join(t.groups())

def stats(rows,key,percent=False,digits=2):
    v=[float(r[key])*(100 if percent else 1) for r in rows if r.get(key,'')!='']
    if not v:return '未完成'
    fmt=lambda x:f'{x:.{digits}f}'
    return f'{fmt(statistics.median(v))} [{fmt(min(v))}, {fmt(max(v))}]'

def table(lines,headers,rows):
    lines+=['','|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']
    lines+=['|'+'|'.join(map(str,r))+'|' for r in rows]

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--report',type=pathlib.Path,required=True);a=p.parse_args();root=a.report
    state=json.loads((root/'batch_state.json').read_text(encoding='utf-8'))
    results=read(root/'results_c2.csv');pairs=read(root/'trajectory_consistency.csv');review=read(root/'loss_review/observations.csv')
    count=len(results)
    assert state['status']=='FINISHED' and state['completed']==count
    assert all(r['valid']=='True' and r['finished_input']=='True' for r in results)
    assert len(review)==sum(int(r['loss_segments']) for r in results) and all(r['observation'] for r in review)
    hashes=read(root/'raw_manifest.csv')
    assert all(hashlib.sha256((root/'raw'/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in hashes)
    assert all(i['exit_code']==0 and i['runner_exit']==0 for i in state['schedule'])
    groups=collections.defaultdict(list)
    for r in results:groups[(r['clip'],r['configuration'])].append(r)
    groups=dict(sorted(groups.items()))
    selected=state['sensitivity_clip']
    lossrows=[];timingrows=[];modulerows=[];telemetry=[]
    for i in state['schedule']:
        folder=root/'analysis'/i['folder']
        for row in read(folder/'timing_summary.csv'):timingrows.append(dict(run=i['folder'],clip=i['clip'],configuration=i['configuration'],run_index=i['run_index'],**row))
        for row in read(folder/'module_summary.csv'):modulerows.append(dict(run=i['folder'],**row))
        for row in read(folder/'telemetry.csv'):
            if row['phase'] not in ('startup','tracking_or_shutdown'):
                raise ValueError('Unknown telemetry phase: '+row['phase'])
            telemetry.append(row)
    for r in review:lossrows.append(dict(r,review_method='人工边界图像观察；可能因素不等于确定因果'))
    for name,rows in [('timing_by_state.csv',timingrows),('module_statistics.csv',modulerows),('loss_review.csv',lossrows)]:write(root/name,rows,list(rows[0]))
    cpu4=sorted({int(r['policy4_cur_khz']) for r in telemetry});cpu6=sorted({int(r['policy6_cur_khz']) for r in telemetry});dmc=sorted({int(r['dmc_cur_hz']) for r in telemetry})
    assert cpu4==[2256000] and cpu6==[2256000] and dmc==[1560000000]
    original=json.loads((root/'original_integrity.json').read_text(encoding='utf-8'))
    assert original['all_unchanged'] and original['all_read_only']
    preview=json.loads((root/'intrinsics_preview.json').read_text(encoding='utf-8'))
    pm=preview['metrics'];pc=preview['checks']
    assert pc['source_sha256_unchanged'] and pc['zero_distortion_identity']
    launch=json.loads((root/'launch.json').read_text(encoding='utf-8'))
    stable=[label(c) for (c,cfg),g in groups.items() if cfg=='provisional' and all(int(r['loss_segments'])==0 for r in g)]
    lines=['# C2 初步 CPU 基线与临时内参画面对比验收','',
        '**临时内参，待标定后重跑。没有真值，不计算 ATE，也不声称米制精度。**','',
        f'{count}/{count} 次退出码为 0、完整处理输入、初始化成功，计时条件通过。各段 3 次，加最稳定片段焦距 0.9/1.1 各 3 次；轮转执行，没有剔除不稳定轨迹或挑选重跑。',
        '初始化后所有重复均无丢失的片段：'+ '、'.join(stable)+'；其余数据存在丢失，不宜直接作为 FPGA 简化比较的数据集。B2 尚未开始。','',
        '## 条件与完整性','',
        f'批次 `{root.name}`，板上任务 `{launch["job_id"]}` 已 SUCCEEDED，exit_code=0；源码 `de62fc00196dc286b5a61b8a1cee57a8cdb6b7c4`（0001–0010，0010 仅增加观测日志）。',
        'GCC 9.4 Release/O3、OpenCV 4.5.5、native，960×720 不缩放、1000 特征/8 层，初始化提取器 5000；关闭可视化、保留按时间戳的默认实时等待。',
        'taskset CPU4–7；CPU performance、DMC performance。散热器、无风扇；0.5 秒监测。运行中 A76 两个 policy 均为 2256 MHz，DMC 为 1560 MHz，未记录降频或热限频。每次 governor 恢复通过；结束后实机检查 CPU interactive、DMC dmc_ondemand，swap=0。',
        f'所有运行最大 SoC 温度 {max(float(r["max_soc_temp_c"]) for r in results):.3f} °C；每次平均温度在 results_c2.csv 中。没有把频率不变当作因果证明或精度证明。',
        f'板端 raw_manifest.csv 的 {len(hashes)} 项 SHA256 与电脑 raw 副本逐项一致；派生分析位于 analysis/，不覆盖 raw。',
        f'本轮重新核对原始 recordings 中 {len(original["files"])} 个文件 SHA256，全部不变且保持只读；证据 original_integrity.json。',
        '原始 H.264/MP4 不改写、不二次编码。输入为此前校验的无损灰度 PNG；时间戳为 PC parser 可用时刻的相对整数纳秒，首帧加 1 秒，不是硬件曝光时刻。损坏帧与时间空缺保留。','',
        '## 跟踪与地图','',
        '表格数值为三次中位数 [最小值, 最大值]。OK 比例以 state_after=2 除以全部输入帧，包含首次成功初始化帧；丢失片段从首次初始化后开始，连续非 OK 含重新初始化。完整输入处理不代表全程成功定位。']
    table(lines,['片段/配置','OK %','初始帧（1起）','初始时间 s','丢失段','地图'],[
        [label(c)+' / '+cfg,stats(g,'state_ok_fraction',True),stats(g,'first_initialization_frame',digits=0),stats(g,'first_initialization_time_s'),stats(g,'loss_segments',digits=0),stats(g,'maps',digits=0)] for (c,cfg),g in groups.items()])
    table(lines,['片段/配置','关键帧','地图点','内点均值','内点中位','内点 P95'],[
        [label(c)+' / '+cfg,stats(g,'keyframes',digits=0),stats(g,'map_points',digits=0),stats(g,'inliers_mean'),stats(g,'inliers_median'),stats(g,'inliers_p95')] for (c,cfg),g in groups.items()])
    lines+=['','关键帧/地图点为 Shutdown 后 Atlas 各最终地图的总数；内点仅统计正常跟踪且记录值≥0的帧，逐帧数值来自 FeatureTimeStats.csv。每次轨迹使用各最终地图独立导出，不把不同地图直接拼接。','',
        '## 耗时与 ORB 占比','',
        '正常跟踪统计按 A2/A3 的 state_before/state_after 分类；首次初始化成功帧归初始化类别，恢复成功帧归正常。ORB 占比只使用正常类别。两种占比为逐帧 ORB/Total 的中位数，以及 ΣORB/ΣTotal。其他模块排除为对齐而补的 0，排除个数保留在 module_statistics.csv。',
        '表格为各次对应统计量的三次中位数 [最小值, 最大值]，单位 ms；没有图像缩放耗时。']
    table(lines,['片段/配置','Total 中位 ms','Total 均值 ms','Total P95 ms','ORB 中位 ms','ORB P95 ms'],[
        [label(c)+' / '+cfg,stats(g,'total_median_ms'),stats(g,'total_mean_ms'),stats(g,'total_p95_ms'),stats(g,'orb_median_ms'),stats(g,'orb_p95_ms')] for (c,cfg),g in groups.items()])
    table(lines,['片段/配置','逐帧比值中位 %','总耗时比 %','Total>33ms %','Total>50ms %'],[
        [label(c)+' / '+cfg,stats(g,'orb_ratio_frame_median',True),stats(g,'orb_ratio_sums',True),stats(g,'total_gt33_fraction',True),stats(g,'total_gt50_fraction',True)] for (c,cfg),g in groups.items()])
    table(lines,['片段/配置','初始化 Total 中位 ms','初始化 ORB 中位 ms','丢失 Total 中位 ms','丢失 ORB 中位 ms'],[
        [label(c)+' / '+cfg,*[stats([r for r in timingrows if r['clip']==c and r['configuration']==cfg and r['category']==kind],metric) for kind in ('initialization','lost') for metric in ('total_median_ms','orb_median_ms')]] for c,cfg in groups])
    lines+=['','没有丢失帧的“丢失耗时”记未完成/无样本，不填 0。计时 Total 是跟踪线程内区间，不包括图像读盘、输入实时等待、日志导出及整个程序壁钟；因多线程竞争，单次差异仍存在。',
        '固定 DMC 后，稳定片段的 ORB 中位耗时仍有约 2–3 ms 的运行间差异；本批次并未证明 A3 的异常由 DDR 调频造成，也不能将其余波动归因于某一未检查因素。','',
        '## 轨迹重复性与焦距敏感性','',
        '每对轨迹选最终关键帧最多的地图，仅取两次共同 OK 时间戳。Sim3 对齐后 RMS 用参考轨迹的 RMS 空间半径归一化，为无量纲；不是 ATE，亦不是相对真值误差。部分地图的公共覆盖不足时明确保留失败，不把单次短地图结果当全程。']
    pg=collections.defaultdict(list)
    for r in pairs:pg[(r['clip'],r['comparison'])].append(r)
    table(lines,['片段/比较','完成/计划对数','归一化 RMS','共同输入覆盖 %'],[
        [label(c)+' / '+cfg,f'{sum(r["status"]=="完成" for r in g)}/{len(g)}',stats([r for r in g if r['status']=='完成'],'normalized_rms',digits=4),stats([r for r in g if r['status']=='完成'],'input_coverage',True)] for (c,cfg),g in sorted(pg.items())])
    failed=[r for r in pairs if r['status']!='完成']
    lines+=['',f'{len(pairs)-len(failed)}/{len(pairs)} 对完成；其余 {len(failed)} 对未完成：最大最终地图共同 OK 帧不足 3。具体运行及原因见 trajectory_consistency.csv。这集中在手持 15:19:23（三对）和 18:46:36（两对），不能据此判断这些运行的全程轨迹一致。',
        f'敏感性片段为 {label(selected)}，按三次最差 OK 比例最高等预设规则选择，未挑单次最好结果。fx/fy 同时乘 0.9/1.1，主点与畸变保持不变。三种焦距配置均三次成功初始化、无后续丢失、单地图；初始化速度改变，轨迹差异以表格和 figures/focal_trajectories.png 为准。',
        f'参考配置重复运行的归一化 RMS 为 {stats(pg[(selected,"within_provisional")],"normalized_rms",True)}%；焦距×0.9 与参考为 {stats(pg[(selected,"provisional_vs_focal_09")],"normalized_rms",True)}%，×1.1 为 {stats(pg[(selected,"provisional_vs_focal_11")],"normalized_rms",True)}%。焦距造成的形状差异大于同配置重复波动，这支持正式标定的必要性；百分数的分母是参考轨迹空间半径，不是飞行距离。',
        '焦距 ±10% 在这个稳定片段上没有破坏跟踪；这不能证明借用焦距正确，也不能外推到所有不稳定片段或真实尺度。首尾同位置尚未确认，闭合误差未完成。','',
        '## 丢失图像审阅','',
        f'全部 {len(review)} 个丢失段均导出前后几帧，并人工查看 10 张联系图；逐段起止秒、长度、恢复/同地图/实际重定位标记、图像观察和可能因素见 loss_review.csv 与 loss_images/*/*/context.json。',
        f'恢复 {sum(r["recovered"]=="True" for r in review)} 段，其中同地图恢复 {sum(r["same_map"]=="True" for r in review)} 段、日志确认实际重定位 {sum(r["actual_relocalization"]=="True" for r in review)} 段；恢复不等同于词袋重定位成功。',
        '视觉观察到三类突出问题：飞行末段贴近低纹理地面；近距离网格重复纹理及视角变化/模糊；大块黑色、方块破损或拖影式块状损坏。某些明显受损图像的 FFmpeg corrupt 标志仍为 False，不能据此认定视频完好。',
        '边界图像只能提示因素，不能证明唯一原因；个别只有一个非 OK 帧的事件未看到明确异常，已如实记为原因未确定。没有仅凭静态图像声称快速旋转的角速度或断言曝光过量。','',
        '## 内参画面对比程序','',
        'scripts/open_intrinsics_preview.ps1 生成并打开可离线查看的 HTML。9 段各取 20%/50%/80% 的真实帧，共 27 帧；原图/校正图分界拖动、整帧切换和参考网格均可用。保持 960×720、同一 K，不裁剪、不通过新 K 放大填边。',
        f'借用模型引起的采样位移平均 {pm["mean_px"]:.6f} px、P95 {pm["p95_px"]:.6f} px、最大 {pm["max_px"]:.6f} px；{pm["source_center_outside_percent"]:.6f}% 的输出像素中心采样位置越界。该数值不是本机标定误差。已检查画面未见剧烈变形，但不能据此确认 fx/fy。',
        f'独立 Brown–Conrady 公式与 OpenCV 映射最大偏差 {pc["analytic_map_max_error_px"]:.8f} px；零畸变映射逐像素恒等；{len(preview["samples"])} 帧生成前后 SHA256 未变化。证据 intrinsics_preview.json，页面截图 figures/intrinsics_viewer.jpg。',
        '源码核对：单目 ORB 在原图提取，Frame::UndistortKeyPoints 校正关键点；此整幅图校正仅用于直观检查，不改 C2 算法与输入。','',
        '## 验收与下一步','',
        f'- 初步 C2 批次、频率控制/恢复、状态和耗时分帧统计、{count} 次 CSV、轨迹重复性/焦距敏感性及{len(review)}段边界图像审阅：完成。',
        '- 5 对轨迹公共覆盖不足：未完成，原因和原始数据保留。',
        '- 正式本机标定、真值精度、首尾闭合误差：未完成。棋盘格脚本已就绪，等待实际视频、内角点数和方格边长。',
        '- 建议下次采集缓慢平移并保持纹理/视差，避免贴近网格和地面；检查视频链路，减少码流损坏。保持正式标定与实验时分辨率、裁剪/防抖一致。',
        '- 待正式标定后重跑每段5次，再由用户选择 B2 数据集；本轮停在 C，不自动进入 B2。','',
        '## 复现','',
        '先 scripts/finish_c.py --batch C2_provisional_20261005_0152（首次收集加 --download）；再 scripts/export_c_loss_images.py、scripts/review_c_losses.py；最后 scripts/report_c_results.py --report reports/c2/C2_provisional_20261005_0152。完整命令见 docs/C_RESULTS_REPRODUCE.md。视觉观察表是人工标签，图像及时间统计可由脚本重新生成。','',
        '## 逐次紧凑摘要','']
    for r in results:lines.append(f'- {label(r["clip"])} / {r["configuration"]} #{r["run_index"]}：完整跑完；ATE不适用（无真值）；CPU/DMC无降频。')
    (root/'C2_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Publication figures use the true timestamp axis, arbitrary SLAM length units.
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt,font_manager
    font=pathlib.Path(os.environ['WINDIR'])/'Fonts/msyh.ttc'
    font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name();plt.rcParams['axes.unicode_minus']=False
    out=root/'figures';out.mkdir(exist_ok=True)
    fig,ax=plt.subplots(figsize=(11,5))
    xs=[]; ys=[]
    for (c,cfg),g in groups.items():
        if cfg!='provisional':continue
        x=label(c);v=[float(r['state_ok_fraction'])*100 for r in g];xs.append(x);ys.append(statistics.median(v));ax.scatter([x]*len(v),v,color='#2468b4')
    ax.plot(xs,ys,'_',markersize=17,color='black',label='三次中位数');ax.set(ylabel='全部输入帧中 OK 占比（%）',title='临时内参，待标定后重跑 · 960×720 · 每段3次');ax.tick_params(axis='x',rotation=30);ax.legend();fig.tight_layout();fig.savefig(out/'tracking_success.png',dpi=300);plt.close(fig)
    items=[i for i in state['schedule'] if i['clip']==selected];ref=next(i for i in items if i['configuration']=='provisional' and i['run_index']==1)
    pts,_,_=trajectory(root/'raw'/ref['folder']);fig,ax=plt.subplots(figsize=(8,6))
    for i in items:
        est,_,_=trajectory(root/'raw'/i['folder']);common=sorted(pts.keys()&est.keys());r=np.array([pts[n] for n in common]);e=np.array([est[n] for n in common]);tr,_=umeyama(r,e);aligned=tr['scale']*(np.array(tr['rotation'])@e.T).T+tr['translation']
        ax.plot(aligned[:,0],aligned[:,1],linewidth=.8,alpha=.7,label=f'{i["configuration"]} #{i["run_index"]}')
    ax.set(xlabel='参考 SLAM X（任意长度单位）',ylabel='参考 SLAM Y（任意长度单位）',title='焦距 ±10% · 共同 OK 帧 Sim3 对齐 · 无真值');ax.axis('equal');ax.legend(fontsize=8,ncol=3);fig.tight_layout();fig.savefig(out/'focal_trajectories.png',dpi=300);plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,4));fr=read(root/'analysis'/ref['folder']/'frames.csv');t=np.array([float(r['timestamp_s']) for r in fr]);t-=t[0]
    ax.plot(t,[float(r['total_ms']) for r in fr],linewidth=.5,label='Total');ax.plot(t,[float(r['orb_ms']) for r in fr],linewidth=.5,label='ORB');ax.axhline(33,color='gray',linestyle='--',label='33 ms');ax.axhline(50,color='red',linestyle=':',label='50 ms');ax.set(xlabel='相对输入时间（s）',ylabel='跟踪线程耗时（ms）',title=f'{label(selected)} #1 · 包含初始化 · 临时内参');ax.legend();fig.tight_layout();fig.savefig(out/'tracking_timing.png',dpi=300);plt.close(fig)
    print('C2_REPORT_READY valid='+str(count)+' raw_hashes='+str(len(hashes))+' visual_review='+str(len(review)))
    for cfg in ['provisional','focal_09','focal_11']:
        g=groups[(selected,cfg)];print(cfg,'OK%',stats(g,'state_ok_fraction',True),'init',stats(g,'first_initialization_frame',digits=0),'Total ms',stats(g,'total_median_ms'),'ORB%',stats(g,'orb_ratio_frame_median',True))
    for comparison in ['within_provisional','provisional_vs_focal_09','provisional_vs_focal_11']:
        g=pg[(selected,comparison)];print(comparison,'normalized RMS',stats(g,'normalized_rms',digits=4))
if __name__=='__main__':main()
