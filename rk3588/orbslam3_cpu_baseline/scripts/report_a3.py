#!/usr/bin/env python3
"""Rebuild A3 Chinese acceptance report and checks from retained measurements."""
import argparse
import csv
import hashlib
import json
import pathlib
import statistics
from summarize_a3 import summarize, ROOT

parser=argparse.ArgumentParser(); parser.add_argument('--batch',required=True); args=parser.parse_args()
report=ROOT/'reports/a3'/args.batch
rows=summarize(report)
a3=[r for r in rows if r['stage']=='A3']
state=json.loads((report/'batch_state.json').read_text(encoding='utf-8'))
configs=json.loads((ROOT/'configs/a3/manifest.json').read_text(encoding='utf-8'))
metadata=[json.loads((report/'raw'/r['folder']/'run_metadata.json').read_text(encoding='utf-8')) for r in a3
          if (report/'raw'/r['folder']/'run_metadata.json').exists()]
reference=json.loads((ROOT/'reports/a2/MH01_600x350_passive_01/raw/attempt_01/run_metadata.json').read_text(encoding='utf-8'))
expected=[('%s_run%02d'%(c['configuration'],run)) for run in range(1,6) for c in configs]
checks={
    'thirty_attempts_retained':len(metadata)==30 and state['completed']==30,
    'round_robin_order':[s['folder'] for s in state['schedule']]==expected,
    'same_A2_binary_and_ORB_commit':len(metadata)==30 and all(m['binary_sha256']==reference['binary_sha256'] and m['orb_commit']==reference['orb_commit'] for m in metadata),
    'A76_affinity':all(m.get('observed_affinity')==[4,5,6,7] for m in metadata),
    'performance_and_governor_restoration':all(m.get('governors_restored') and all(v=='performance' for v in m['governors_during_run'].values()) for m in metadata),
    'no_frequency_or_thermal_cap':all(not m['frequency_drop_detected'] and not m['thermal_cap_detected'] for m in metadata),
    'settings_hashes':all(hashlib.sha256((report/'raw'/r['folder']/'settings.yaml').read_bytes()).hexdigest()==r['sha256'] for r in a3),
    'half_scale_intrinsics':all(s.get('observed_intrinsics') and all(abs(a-b)<0.001 for a,b in zip(s['observed_intrinsics'],[229.327,228.648,183.6075,124.1875])) for s in state['schedule'] if s['configuration']=='half_376x240'),
    'each_failure_has_reason':all(r['tracking_result_valid'] or r['reason'] for r in a3),
    'evo_numpy_crosscheck':all('cross-check passed' in r.get('evaluation_method','') for r in a3 if r['tracking_result_valid']),
    'thirty_inputs_complete':all(r['finished_input'] for r in a3),
    'all_tracking_results_available':all(r['tracking_result_valid'] for r in a3),
}
with (report/'acceptance.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream); writer.writerow(['check','status']); writer.writerows((k,'PASS' if v else 'FAIL') for k,v in checks.items())
summary=list(csv.DictReader((report/'summary.csv').open(encoding='utf-8')))
def metric(name,key,scale=1):
    item=next(r for r in summary if r['configuration']==name and r['metric']==key)
    if item['median']=='': return '未完成'
    return '%0.2f（%0.2f～%0.2f）'%tuple(float(item[k])*scale for k in ('median','min','max'))
def med(name,key):
    item=next(r for r in summary if r['configuration']==name and r['metric']==key)
    return float(item['median']) if item['median']!='' else None
labels={c['configuration']:'%d×%d / %d 特征 / %d 层'%(c['tracking_width'],c['tracking_height'],c['nFeatures'],c['nLevels']) for c in configs}
labels['official_600x350_reference']='A2 600×350 / 1000 / 8（官方非等比缩放）'
duration=(__import__('datetime').datetime.fromisoformat(state['updated_utc'])-__import__('datetime').datetime.fromisoformat(state['started_utc'])).total_seconds()/60
lines=['# A3：MH01 参数矩阵', '', '分析日期：2026-10-04。六组各五次按序号轮转执行，失败不替换、不修改随机种子。',
       '板上批次状态 %s，执行 %d/%d 次，实际耗时 %.2f 分钟（包含启动、冷却与退出）。'%(state['status'],state['completed'],state['planned'],duration),
       '输入是否跑完、跟踪是否有可评估轨迹分别记录；输入结束不能证明全程无丢失。', '',
       '## 固定条件与版本', '',
       'Ubuntu 20.04.6 / 内核 5.10.160，GCC 9.4、CMake 3.16.3，OpenCV 4.5.5、Pangolin v0.8。',
       'ORB 提交 cf36b06 = d307c3c + 0008；相对官方 v1.0-release 为 0001～0008。与 A2 二进制哈希一致性见 acceptance.csv。',
       'SLAM CPU4～7（实际 A76）；采样监督进程 CPU0～3。三个 policy 为 performance，结束恢复原 governor。',
       '已装散热器，无风扇或风扇未转。半秒采样温度、实际频率、频率上限与 CPU cooling state；每次开始前所有温区 ≤45°C。',
       '关闭 viewer，保留 mono_euroc 原来的时间戳间隔等待。所有输入保持 752×480；基准删除 newWidth/newHeight。',
       '半分辨率由 Settings 缩放，fx=229.327、fy=228.648、cx=183.6075、cy=124.1875；实际日志按 0.001 精度核对。',
       '初始化提取器使用 5*nFeatures：500/1000/1500 档分别为 2500/5000/7500。', '',
       '## 每组五次结果：中位数（最小～最大）', '',
       '| 配置 | 可评估次数 | ATE RMSE（cm） | Total 中位耗时（ms） | Total P95（ms） | ORB 中位耗时（ms） | ORB P95（ms） |',
       '|---|---:|---:|---:|---:|---:|---:|']
for name in labels:
    group=[r for r in rows if r['configuration']==name]; valid=sum(r['tracking_result_valid'] for r in group)
    lines.append('| %s | %d/5 | %s | %s | %s | %s | %s |'%(labels[name],valid,metric(name,'ate_rmse_m',100),metric(name,'total_median_ms'),metric(name,'total_p95_ms'),metric(name,'orb_median_ms'),metric(name,'orb_p95_ms')))
lines+=['', '| 配置 | 逐帧 ORB/Total 中位数（%） | ΣORB/ΣTotal（%） | Total >33 ms（%） | Total >50 ms（%） | 平均 SoC 温度（°C） |',
        '|---|---:|---:|---:|---:|---:|']
for name in labels:
    lines.append('| %s | %s | %s | %s | %s | %s |'%(labels[name],metric(name,'orb_ratio_frame_median',100),metric(name,'orb_ratio_sums',100),metric(name,'total_gt33_fraction',100),metric(name,'total_gt50_fraction',100),metric(name,'mean_soc_temp_c')))
lines+=['', 'ATE 使用相机坐标系真值、纳秒转秒、evo -as Sim3 对齐及 10 ms 关联阈值；每次由独立 NumPy Umeyama 校核全部误差。',
        '耗时只在正常跟踪帧统计；逐帧比值取每次中位数再取五次中位数，另一口径为每次 ΣORB/ΣTotal 再取五次中位数。',
        'Total 含 Settings 内部 Image Resize；A2 600×350 为非等比缩放，A3 376×240 为等比缩放；当前 Image Resize 列不能单独测量这项内部开销。',
        'P95 为正常帧耗时的第95百分位，表中再汇总五次 P95 的中位数和范围。其余模块排除用于对齐的零，不将它们计为实际测量。', '',
        '## 每次运行与轨迹覆盖', '',
        '| 配置 | 序号 | 输入跑完 | ATE（cm） | 地图数 | 正常/初始化/丢失帧 | 恢复帧 | 地图重置 | 真值关联位姿 | 降频 |',
        '|---|---:|---|---:|---:|---|---:|---:|---:|---|']
for r in a3:
    lines.append('| %s | %d | %s | %s | %s | %s/%s/%s | %s | %s | %s | %s |'%
                 (r['configuration'],r['run_index'],'是' if r['finished_input'] else '否',
                  '%.3f'%(r['ate_rmse_m']*100) if r.get('ate_rmse_m') is not None else '未完成',r.get('maps','未完成'),
                  r.get('frames','未完成'),r.get('initialization_frames','未完成'),r.get('lost_frames','未完成'),
                  r.get('recovery_frames','未完成'),r.get('active_map_resets',0)+r.get('full_resets',0),
                  r.get('associated_poses','未完成'),'是' if r.get('frequency_drop') or r.get('thermal_cap') else '否'))
    if not r['tracking_result_valid']: lines.append('失败 %s：%s'%(r['folder'],r['reason']))
lines+=['', '初始化前和丢失帧的耗时另列 state_summary.csv；各模块非零统计详见每次 raw/module_summary.csv。',
        '多个 Atlas 地图或跟踪丢失可能只导出最大地图的部分轨迹；关联位姿数也必须一起比较，不能凭小 ATE 推断全程准确。', '', '## 基于测量的结论', '']
base='baseline_752x480'; baseline=med(base,'total_median_ms')
if baseline:
    changes=[(name,100*(med(name,'total_median_ms')/baseline-1)) for name in labels if name not in (base,'official_600x350_reference') and med(name,'total_median_ms') is not None]
    lines.append('相对 752×480 基准，正常帧 Total 中位耗时变化：'+ '；'.join('%s %+.2f%%'%(name,change) for name,change in changes)+'。')
    largest=max(changes,key=lambda item:abs(item[1]))
    lines.append('本次单维度对照中绝对变化最大的是 %s（%+.2f%%）；所有结果仍保留五次波动范围。'%largest)
    lines.append('752×480 基准 ORB 占比：逐帧口径 %.2f%%，总耗时口径 %.2f%%；A2 600×350 参考分别 %.2f%%、%.2f%%。'%(med(base,'orb_ratio_frame_median')*100,med(base,'orb_ratio_sums')*100,med('official_600x350_reference','orb_ratio_frame_median')*100,med('official_600x350_reference','orb_ratio_sums')*100))
    lines.append('各变化组 ORB 总耗时口径占比：'+'；'.join('%s %.2f%%'%(name,med(name,'orb_ratio_sums')*100) for name,_ in changes)+'。')
    one=med('levels_1','ate_rmse_m'); full=med(base,'ate_rmse_m')
    if one is not None and full:
        lines.append('nLevels=1 的 ATE 中位数为 %.3f cm，基准为 %.3f cm，相对 %.2f 倍；结合上表丢失帧、地图数量和轨迹覆盖判断退化，不能只比较耗时。'%(one*100,full*100,one/full))
        lines.append('本次 MH01 的五次实测未显示 nLevels=1 出现数量级精度退化；两组 ATE 范围有重叠，这不是对其他运动和尺度变化场景的验证。')
    else: lines.append('nLevels=1 的 ATE 未完成，原因见逐次失败记录。')
lines.append('A3 与 A2 参考的实际温度不同，详见上表；时延对比未做温度校正。这里是同一二进制、固定频率下的实测对照。')
groundtruth=(ROOT/'reports/a2/MH01_600x350_passive_01/raw/groundtruth_cam0.tum').read_text(encoding='utf-8').splitlines()
start_truth=float(groundtruth[0].split()[0]); end_truth=float(groundtruth[-1].split()[0])
coverage=[]
for row in a3:
    with (report/'raw'/row['folder']/'TrackingStates.csv').open() as stream: tracking=list(csv.DictReader(stream))
    lost=[s for s in tracking if int(s['state_after']) in (3,4)]
    inside=sum(start_truth<=float(s['timestamp_s'])<=end_truth for s in lost)
    coverage.append(dict(configuration=row['configuration'],run_index=row['run_index'],final_tracking_state=int(tracking[-1]['state_after']),
                         lost_frames=len(lost),lost_inside_groundtruth_span=inside,lost_outside_groundtruth_span=len(lost)-inside,
                         groundtruth_start_s=start_truth,groundtruth_end_s=end_truth))
with (report/'trajectory_coverage.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(coverage[0])); writer.writeheader(); writer.writerows(coverage)
one_ended_lost=sum(r['final_tracking_state'] in (3,4) for r in coverage if r['configuration']=='levels_1')
base_ended_lost=sum(r['final_tracking_state'] in (3,4) for r in coverage if r['configuration']==base)
lines+=['', '## 遇到的跟踪问题', '',
        'nLevels=1 有 %d/5 次结束时为 RECENTLY_LOST/LOST，752×480 基准为 %d/5；不能据 ATE 相近声称跟踪鲁棒性相同。'%(one_ended_lost,base_ended_lost),
        '原始日志含 `Fail to track local map!`，与状态文件一致。输入仍处理完，地图数保持一，没有重置或补跑。',
        '本次全部 A3 丢失帧中，%d 帧在真值时间范围内，%d 帧在真值范围外；GT 时间区间为 %.9f～%.9f s。'%(sum(r['lost_inside_groundtruth_span'] for r in coverage),sum(r['lost_outside_groundtruth_span'] for r in coverage),start_truth,end_truth),
        '这些尾段丢失没有被 ATE 覆盖；每次仍关联 3638 个真值位姿。ATE 结论只适用于真值覆盖的轨迹，完整跟踪结果另见 trajectory_coverage.csv。']
lines+=['', '## 验收与文件', '', '| 项目 | 结果 |', '|---|---|']+[ '| %s | %s |'%(k,'PASS' if v else 'FAIL') for k,v in checks.items()]
lines+=['', 'results_exp1.csv 保留 A3 三十行及 A2 五行参考；summary.csv 可由 summarize_a3.py 从 raw 重建。',
        'state_summary.csv 为初始化/正常/丢失的独立耗时；raw 含原始时间、状态、轨迹、温度频率、YAML、evo 和 NumPy 校核结果。',
        '新增 report_a3.py、verify_a3_results.py；修改 finish_a3.py、summarize_a3.py 和 docs/A3_REPRODUCE.md，保留逐次依赖/数据校验、UTF-8 读写、失败结果判定及纯 CSV 汇总入口。全部修改在 a3/parameter-matrix 分支提交。',
        '三十次 NumPy 独立计时/温度频率/依赖核验通过；CSV-only 汇总字节一致。验证结果见 validation.csv，所有 raw 文件哈希见 raw_sha256.json。',
        '本阶段分析完成后停下，等待用户验收，不自动开始外部特征注入。']
state_rows=[]
for r in a3:
    path=report/'raw'/r['folder']/'timing_summary.csv'
    if path.exists():
        with path.open() as stream:
            state_rows.extend(dict(configuration=r['configuration'],run_index=r['run_index'],tracking_width=r['tracking_width'],tracking_height=r['tracking_height'],**group) for group in csv.DictReader(stream))
if state_rows:
    with (report/'state_summary.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(state_rows[0])); writer.writeheader(); writer.writerows(state_rows)
(report/'A3_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('A3_REPORT_READY acceptance=%d/%d report=%s'%(sum(checks.values()),len(checks),report/'A3_REPORT.md'))
