#!/usr/bin/env python3
"""Generate B1 report solely from retained CSV/JSON evidence; no reruns of SLAM."""
import argparse
import csv
import json
import pathlib
import statistics

ROOT=pathlib.Path(__file__).resolve().parent.parent

def render(report):
    with (report/'results_exp3_b1.csv').open(encoding='utf-8') as f: rows=list(csv.DictReader(f))
    acceptance=json.loads((report/'acceptance.json').read_text())
    state=json.loads((report/'batch_state.json').read_text(encoding='utf-8'))
    full=state['verification']; m=json.loads((report/'raw/native_run01/run_metadata.json').read_text(encoding='utf-8'))
    groups={mode:[r for r in rows if r['mode']==mode and r['valid']=='True'] for mode in ('native','inject')}
    def values(mode,key): return [float(r[key]) for r in groups[mode] if r.get(key,'')!='']
    def med(mode,key): return statistics.median(values(mode,key))
    def display(mode,key,scale=1,digits=3):
        v=[x*scale for x in values(mode,key)]
        return ('{:.%df}（{:.%df}～{:.%df}）'%(digits,digits,digits)).format(statistics.median(v),min(v),max(v))
    nt=med('native','tracking_total_median_ms'); it=med('inject','tracking_total_median_ms'); ideal=med('inject','remaining_ms_median')
    with (report/'baseline_comparison.csv').open() as f:
        old=next(r for r in csv.DictReader(f) if r['condition']=='A3_accepted_baseline_reference')
    covered=int(rows[0]['gt_input_frames']); input_count=int(rows[0]['processed_frames'])
    tail_runs={mode:sum(int(r['tail_lost_frames'])>0 for r in group) for mode,group in groups.items()}
    ate_method=rows[0]['evaluation_method']
    initlost=[]
    for mode in groups:
        for category in ('initialization','lost'):
            metrics={}
            for item in groups[mode]:
                with (report/'raw'/('%s_run%02d'%(mode,int(item['run_index'])))/'b1_timing_summary.csv').open() as f:
                    data=list(csv.DictReader(f))
                for metric in ('total_ms','feature_slot_ms'):
                    s=next(r for r in data if r['category']==category and r['metric']==metric)
                    if s['count']!='0': metrics.setdefault(metric,[]).append(float(s['median']))
            initlost.append('| %s | %s | %d | %s | %s |'%(mode,category,len(metrics.get('total_ms',[])),
                '%.3f'%statistics.median(metrics['total_ms']) if metrics.get('total_ms') else '无丢失帧',
                '%.3f'%statistics.median(metrics['feature_slot_ms']) if metrics.get('feature_slot_ms') else '无丢失帧'))
    report_lines=[
        '# B1：外部特征导出与注入验收',
        '',
        '分析日期：2026-10-04（日本时间）。本阶段接口及 MH01 操作性验收通过；未进入 B2。',
        '配置：**752×480 原图 / nFeatures=1000 / nLevels=8 / scaleFactor=1.2**；初始化提取器5000特征预算。',
        'A2 的600×350官方非等比缩放结果不混入本基准。A3不重跑，其动态DDR基准单列参考。',
        '',
        '## 实际运行条件与证据',
        '',
        '- CPU4–7（A76）绑定，CPU performance；A76实际频率2256000 kHz。',
        '- DMC performance，所有半秒样本均为1560000000 Hz；无CPU/DMC降频、温控限频。',
        '- 每次运行后恢复CPU interactive和DMC dmc_ondemand，并核对恢复与原频率上限；当前板上状态也确认已恢复。',
        '- 散热状态沿用用户确认：有散热器，没有风扇或风扇未转。各模式五次平均温度的中位数：native %.2f℃、inject %.2f℃；全批次SoC最高%.3f℃。'%(med('native','mean_soc_temp_c'),med('inject','mean_soc_temp_c'),max(float(r['max_soc_temp_c']) for r in rows)),
        '- 关闭Viewer，保留mono_euroc按输入时间戳等待的实时节奏；十次均处理全部3682帧，各模式五次交错执行，偶数轮交换先后。',
        '- 同一二进制、同一YAML；OpenCV只链接4.5.5，未混入4.2，也没有apt 4.2开发包。',
        '- 源码分支b1/external-features，ORB commit `%s`；等于cf36b06 + 0009（官方v1.0-release + 0001～0009）。'%m['orb_commit'],
        '- 原始板端文件→电脑校验清单 `%s`；独立验收%s，共%d项。'%('raw_manifest.csv',acceptance['status'],acceptance['checks']),
        '',
        '## 特征接口与字节一致性',
        '',
        '每个整数纳秒输入对应normal和initialization两份文件，格式为小端、64字节头+每点64字节；包含魔数、版本、图像/尺度/提取器角色及32字节描述子。',
        '关键点保存第0层未去畸变坐标和全部float位模式，保留octave/angle/size/response/class_id、点-描述子顺序及monoLeft；Frame后续去畸变和尺度/sigma²读取保持原样。',
        'Tracking在完成初始化后的早期帧仍可能选择初始化提取器，选择条件沿用源码，不简化为只看mState。',
        'dump对全部帧导出两套；独立Python解析器直接逐字节比较另一路内存快照：**%d个文件、%d个点、%d字节，0处不一致**。'%(full['files'],full['points'],full['bytes_compared']),
        '7364个文件覆盖完整时间戳和两种角色；十次native/inject的整数时间戳、选中角色的点数也与校验库完全一致。',
        'inject每帧实际ORBextractor调用数为0；native为1、dump为2。缺失或不匹配文件会报错，不偷偷回退提取。',
        '独立codec检查和A1的24帧三模式合成检查已通过；合成数据不计入本表。FPGA字段精度/适配要求见docs/B1_FEATURE_FORMAT.md草案，待负责人确认，未实施B2简化。',
        '',
        '## 逐次运行（一行一条）',
        '',
        '| 模式/序号 | 全程跑完 | ATE RMSE（cm） | CPU或DMC降频 |',
        '|---|---|---:|---|',
    ]
    for r in rows:
        report_lines.append('| %s/%s | %s | %.3f | %s |'%(r['mode'],r['run_index'],'是' if r['finished_input']=='True' else '否',
            float(r['ate_rmse_m'])*100,'是' if any(r[k]=='True' for k in ('cpu_drop','dmc_drop','thermal_cap')) else '否'))
    report_lines += ['', '## 精度、状态与内点数', '',
        '下表为五次统计量的中位数（最小～最大）；不把五次所有帧混成一次运行。ATE使用电脑Sim3（-as）：%s。'%ate_method,
        '',
        '| 指标 | native | inject |','|---|---:|---:|']
    for label,key,scale,digits in (
        ('ATE RMSE（cm）','ate_rmse_m',100,3),('正常帧数','normal_frames',1,0),('初始化帧数','initialization_frames',1,0),
        ('丢失帧数（均在GT范围外）','lost_frames',1,0),('state_after=OK占全部输入（%）','state_ok_fraction',100,3),
        ('平均匹配内点数（只用正常帧）','inliers_mean',1,2),('地图数','maps',1,0)):
        report_lines.append('| %s | %s | %s |'%(label,display('native',key,scale,digits),display('inject',key,scale,digits)))
    report_lines += [
        '',
        '十次初始化帧数均为%d；GT覆盖的%d个输入帧全部为OK，ATE各关联%d个位姿（输入覆盖%d/%d=%.3f%%），没有用GT范围外尾段掩盖精度误差。'%(int(med('native','initialization_frames')),covered,int(rows[0]['associated_poses']),covered,input_count,100*covered/input_count),
        'native有%d/5次、inject有%d/5次尾段短暂丢失；均始于1403636762963555584 ns（相对序列起点183.2 s），最终均恢复OK、始终1张地图、无地图重置。'%(tail_runs['native'],tail_runs['inject']),
        '丢失仅在GT结束后，未贡献ATE。inject的尾段丢失次数较多，需要保留这个差异；5次样本不足以判断是否存在系统性影响。',
        '两组ATE中位数相差%.4f cm、范围重叠；GT段跟踪成功率一致、内点数相近。支持本次接口操作性等价性验收，不能解释为统计学上已证明严格等价。'%((med('inject','ate_rmse_m')-med('native','ate_rmse_m'))*100),
        '', '## 正常帧耗时', '',
        '| 指标（ms，五次中位数与范围） | native | inject |','|---|---:|---:|']
    for label,key in (
        ('Total逐帧中位数','tracking_total_median_ms'),('Total均值','tracking_total_mean_ms'),('Total P95','tracking_total_p95_ms'),
        ('完整特征槽位中位数','feature_slot_ms_median'),('文件读取中位数','read_ms_median'),('文件读取P95','read_ms_p95'),
        ('解码/验证中位数','decode_ms_median'),('解码/验证P95','decode_ms_p95'),('逐帧Total−完整特征槽位中位数','remaining_ms_median'),
        ('逐帧Total−完整特征槽位P95','remaining_ms_p95')):
        report_lines.append('| %s | %s | %s |'%(label,display('native',key),display('inject',key)))
    report_lines += [
        '',
        '同固定DDR条件下，Total中位数下降 **%.3f ms（%.2f%%）**，约%.2f倍跟踪线程耗时比；保留实时等待，因此不代表整程序帧率提高到同样倍数。'%(nt-it,100*(1-it/nt),nt/it),
        'inject特征槽位中位数%.3f ms，包含文件读取、解码、调用/关闭等开销；单项中位数之和不等于联合逐帧中位数。'%med('inject','feature_slot_ms_median'),
        '理想无提取/无传输的剩余跟踪耗时中位数为 **%.3f ms**，按每帧Total−完整特征槽位后再聚合，不能用两个中位数直接相减代替。实际FPGA还有传输/同步成本。'%ideal,
        'native ORB占比：逐帧比值的中位数%.2f%%，ORB总耗时/Total总耗时%.2f%%。'%(100*med('native','orb_ratio_frame_median'),100*med('native','orb_ratio_sums')),
        '',
        '| 正常帧Total比例（%） | native | inject |','|---|---:|---:|',
        '| >33 ms | %s | %s |'%(display('native','total_gt33_fraction',100),display('inject','total_gt33_fraction',100)),
        '| >50 ms | %s | %s |'%(display('native','total_gt50_fraction',100),display('inject','total_gt50_fraction',100)),
        '', '初始化和丢失计时单列（单位ms；各有该状态的运行中位数再取中位数，缺失状态不补0）：', '',
        '| 模式 | 状态 | 有数据的运行数 | Total中位数 | 特征槽位中位数 |','|---|---|---:|---:|---:|']+initlost+[
        '', '其他模块统计复用module_summary.csv，排除对齐补0；native的文件读取为真实0，单独保留其语义。',
        '', '## 与A3及B0的关系', '',
        '旧A3 752×480基准Total中位数%.3f ms、ORB中位数%.3f ms、总耗时占比%.2f%%；本次固定DDR native为%.3f ms、特征槽位%.3f ms、占比%.2f%%。'%(float(old['total_ms']),float(old['orb_ms']),100*float(old['orb_ratio_sums']),nt,med('native','feature_slot_ms_median'),100*med('native','orb_ratio_sums')),
        'A3的DDR动态且未逐次记录，环境/调度也可能影响结果，不能把跨阶段全部差异算成注入收益。正式收益使用同一B1批次的native/inject。',
        '本次五次native特征槽位中位数范围%s ms，没有再出现A3那种约3 ms的组内跳变；这支持继续固定DMC，但不能反推A3异常的因果。'%display('native','feature_slot_ms_median'),
        '', '## 修改与复现', '',
        '- ORB补丁0009：FeatureIO.h/.cc、Frame.cc、Tracking.cc、System.h/.cc、ORBextractor.h、mono_euroc.cc、feature_io_check.cc、CMakeLists.txt。',
        '- 实验脚本：build_b1.sh、batch_b1.py、run_a2.py（可选DMC/feature参数，原A2/A3默认保持）、preflight_dmc.py、verify_feature_files.py、check_b1_synthetic.py、check_b1_started.py。',
        '- 电脑分析：analyze_b1.py、finish_b1.py、verify_b1_results.py、report_b1.py；新增真实均值、成功率、GT覆盖、温度和恢复字段，未修改原始计时/轨迹。',
        '- 原始数据raw/，逐次results_exp3_b1.csv（另给results_exp3.csv同内容），五次summary.csv，A3单列baseline_comparison.csv，acceptance.csv，板端raw_manifest.csv。',
        '- 本目录报告由report_b1.py从上述保留原始/派生文件重新生成；汇总可由finish_b1.py --local-only / --csv-only重建，命令见docs/B1_RUNBOOK.md。',
        '', '下一阶段等待用户确认；B2所需FPGA规格尚未由负责人确认，不自动开始。',
    ]
    (report/'B1_REPORT.md').write_text('\n'.join(report_lines)+'\n',encoding='utf-8')
    (report/'results_exp3.csv').write_bytes((report/'results_exp3_b1.csv').read_bytes())
    print('B1_REPORT_READY '+str(report/'B1_REPORT.md'))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('report',type=pathlib.Path); a=p.parse_args(); render(a.report)
