"""Read-only raw acceptance and reproducible decision report; never runs SLAM."""
import argparse
import collections
import csv
import hashlib
import json
import math
import pathlib
import shutil
import statistics
import zipfile
import io
import numpy as np

FIELDS=['initialization_frame','post_init_ok_fraction','loss_segments',
        'loss_duration_s','maps','ate_rmse_m','inliers_median',
        'feature_count_mean','state_ok_fraction']


def rows(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def load(p):return json.loads(p.read_text(encoding='utf-8'))


def close(a,b):
    assert math.isclose(float(a),float(b),abs_tol=1e-10,rel_tol=1e-10),(a,b)


def label(d):
    return 'MH01' if d=='MH01' else ('Tello 18:49:29' if 'T184929' in d else 'Tello 20:06:48')


def native_path(value):
    parts=pathlib.PurePosixPath(value).parts
    if len(parts)>3 and parts[1]=='mnt' and len(parts[2])==1:
        return pathlib.Path(parts[2].upper()+':/').joinpath(*parts[3:])
    return pathlib.Path(value)


def span(r,k,scale=1,digits=2):
    if r.get(k+'_median','')=='':return '未完成'
    a,b,c=(float(r[k+'_'+s])*scale for s in ['median','min','max'])
    return f'{a:.{digits}f} [{b:.{digits}f}, {c:.{digits}f}]'


def main():
    p=argparse.ArgumentParser();p.add_argument('--batch-root',required=True)
    p.add_argument('--report-name',default='report_corrected');a=p.parse_args()
    batch=pathlib.Path(a.batch_root);review=batch/a.report_name
    state=load(batch/'batch_state.json');coordinator=load(batch.with_name(batch.name+'_coordinator')/'state.json')
    assert state['status']==coordinator['status']=='FINISHED_AWAIT_LAYER_DECISION'
    assert coordinator['power_restore_exit_code']==0 and coordinator['awake_released']
    schedule=state['schedule'];assert len(schedule)==state['completed']==90
    results=rows(review/'results.csv');summary=rows(review/'summary_by_layers.csv')
    pairs=rows(review/'native_differences.csv')
    keys=lambda r:(r['dataset'],r['variant'],int(r['run_index']))
    assert len({keys(r) for r in results})==90
    assert {keys(r) for r in results}=={keys(r) for r in schedule}
    datasets={d['name']:d for d in load(batch/'configs/manifest.json')['datasets']}
    failures=[];ate_coverage=[];all_rows=0
    for r in results:
        raw=batch/'runs'/r['folder'];meta=load(raw/'run_metadata.json')
        states=rows(raw/'TrackingStates.csv');features=rows(raw/'FeatureTimeStats.csv');maps=rows(raw/'MapStateStats.csv')
        assert len(states)==len(features)==len(maps)==int(r['completed_frames'])
        all_rows+=len(states)
        for i,(s,f,m) in enumerate(zip(states,features,maps)):
            assert all(int(x['frame_index'])==i for x in [s,f,m])
            assert int(f['extractor_calls'])==(1 if r['variant']=='native' else 0)
        ok=[i for i,s in enumerate(states) if s['state_after']=='2']
        assert len(ok)==int(r['state_ok_frames'])
        if ok:
            assert ok[0]+1==int(r['initialization_frame'])
            tail=states[ok[0]+1:]
            close(sum(s['state_after']=='2' for s in tail)/len(tail),r['post_init_ok_fraction'])
            expected_losses=sum(s['state_after']!='2' and (i==0 or tail[i-1]['state_after']=='2') for i,s in enumerate(tail))
            assert expected_losses==int(r['loss_segments'])
        if r['status']=='FINISHED':
            assert meta['status']=='FINISHED' and meta['exit_code']==0
            assert len(states)==datasets[r['dataset']]['full_frames']
            assert len(rows(raw/'Diagnostics_maps.csv'))==int(r['maps'])
            inliers=[int(f['inliers']) for s,f in zip(states,features) if s['state_after']=='2' and int(f['inliers'])>=0]
            close(statistics.median(inliers),r['inliers_median'])
            if r['dataset']=='MH01':
                analysis=review/'analysis'/r['folder'];ate=load(analysis/'ate.json')
                assert 'NumPy cross-check passed' in ate['evaluation_method']
                close(ate['ate_rmse_m'],r['ate_rmse_m']);close(ate['numpy_rmse_m'],r['ate_rmse_m'])
                with zipfile.ZipFile(analysis/'ape.zip') as z:
                    errors=np.load(io.BytesIO(z.read('error_array.npy')),allow_pickle=False)
                close(np.sqrt(np.mean(errors**2)),r['ate_rmse_m'])
                association=load(analysis/'timestamp_association.json')
                assert association['kept_ok_unique_frames']==len(ok)
                assert association['kept_ok_rows']==int(r['ate_exported_ok_poses'])
                gt=native_path(datasets['MH01']['path'])/'mav0/state_groundtruth_estimate0/data.csv'
                with gt.open() as f:truth=[int(x[0]) for x in csv.reader(f) if x and not x[0].startswith('#')]
                eligible=sum(truth[0]<=int(f['timestamp_ns'])<=truth[-1] for f in features)
                ate_coverage.append(dict(variant=r['variant'],run_index=r['run_index'],associated=int(r['ate_associated']),
                    eligible_frames=eligible,coverage=int(r['ate_associated'])/eligible,
                    max_rounding_ns=association['max_export_rounding_ns']))
        else:
            evidence=dict(dataset=r['dataset'],variant=r['variant'],run=r['run_index'],completed_frames=len(states),
                classification=r['classification'],reason=r.get('failure',''),stack_path='',stack_summary='')
            if r['classification']=='CANDIDATE_HANG_RETAINED':
                snap=raw/'hang_snapshot';stack=snap/'threads.gdb.txt'
                assert meta['stack_capture_ok'] and meta['snapshot_saved_before_signal_utc']
                text=stack.read_text(encoding='utf-8',errors='replace')
                assert 'Tracking::Relocalization' in text and '[Inferior' in text
                assert len(list(snap.glob('*_wchan.txt')))>=3 and len(list(snap.glob('*_status.txt')))>=3
                evidence.update(stack_path=str(stack),stack_summary='Tracking::Relocalization; '+
                    ('MLPnPsolver/Eigen' if 'MLPnPsolver' in text else 'Optimizer::PoseOptimization'))
            else:
                assert r['classification']=='INPUT_SETUP_FAILURE_RETAINED_NO_RETRY' and not states
            failures.append(evidence)
    for s in summary:
        group=[r for r in results if r['dataset']==s['dataset'] and r['variant']==s['variant']]
        valid=[r for r in group if r['status']=='FINISHED']
        assert int(s['attempts'])==5 and int(s['valid'])==len(valid)
        for field in FIELDS:
            values=[float(r[field]) for r in valid if r.get(field,'')!='']
            for name,fn in [('median',statistics.median),('min',min),('max',max)]:
                if values:close(fn(values),s[field+'_'+name])
                else:assert s[field+'_'+name]==''
    out=pathlib.Path(__file__).resolve().parents[1]/'reports/golden_decision'/batch.name
    out.mkdir(parents=True,exist_ok=True)
    proof=(batch/'runtime_revalidation.txt').read_text(encoding='utf-8-sig').strip()
    assert proof.startswith('ACCEPTED_LINUX_RUNTIME_PASS files=51 ')
    shutil.copy2(batch/'runtime_revalidation.txt',out/'runtime_revalidation.txt')
    for name in ['results.csv','summary_by_layers.csv','native_differences.csv']:
        shutil.copy2(review/name,out/name)
    # Archive text with explicit LF; authoritative raw and reviewed inputs remain unchanged.
    for name in ['results.csv','summary_by_layers.csv','native_differences.csv','runtime_revalidation.txt']:
        path=out/name;path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))
    audit=dict(status='COMPLETED_WITH_RETAINED_FAILURES',batch=batch.name,platform='x86 PC / WSL2',
        slots=90,finished=sum(r['status']=='FINISHED' for r in results),failures=failures,
        raw_diagnostic_rows_checked=all_rows,summary_groups_checked=len(summary),ate_coverage=ate_coverage,
        shape_pairs=collections.Counter(r['status'] for r in pairs),power_restored=True,awake_released=True,
        runtime_revalidation=proof,
        original_report_retained=str(batch/'report'),corrected_report=str(review),spec_v1_0_updated=False)
    (out/'acceptance.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    lines=['# G1 层数决策轮验收与结果','',f'批次：`{batch.name}`。平台：**x86 PC / WSL2**。',
        'Tello：**借用内参，未本机标定**；轨迹形状需正式标定后重算。PC 耗时不用于 RK3588 或 FPGA 性能结论。',
        '',f'90 个槽位全部结束：81 全程完成，9 失败（1 输入设置失败、8 重定位路径卡住）；失败未替换。',
        '进程完成不等于全程无丢失。统计仅取全程完成且初始化成功的运行，失败的部分状态另外保留；native/MH01 只有 4 个有效重复。',
        '', '## 配置与口径','',
        'native 为本轮新跑的原版；V0 是 G1 定点控制（关闭 F/G/A32），不是历史 B1 字节等价控制。',
        'L8/L4/L2/L1 均使用固定 FAST20、网格单点不回填、A32、标准 BRIEF 与高斯模糊，仅层数不同，scaleFactor 均为 1.2。',
        '表格为中位数 [最小, 最大]；OK 占比仅统计首次初始化成功之后的全部剩余输入帧，含后续重置/初始化帧。',
        '', '## 全程结果','',
        '|数据|配置|有效/计划|初始化帧|初始化后 OK %|丢失段数|最终地图数|ATE RMSE cm|内点中位数|',
        '|---|---|---|---|---|---|---|---|---|']
    for s in summary:
        lines.append('|'+ '|'.join([label(s['dataset']),s['variant'],s['valid']+'/5',
            span(s,'initialization_frame',digits=0),span(s,'post_init_ok_fraction',100),
            span(s,'loss_segments',digits=0),span(s,'maps',digits=0),
            span(s,'ate_rmse_m',100) if s['dataset']=='MH01' else '无真值，不适用',span(s,'inliers_median',digits=1)])+'|')
    lines+=['','## 实拍轨迹差异与覆盖','',
        'Sim3 归一化 RMS 为无量纲相对形状差异，除以参考轨迹位置离散程度；不是 ATE、绝对精度或真实尺度。仅比较最大最终地图的共同 OK 帧。',
        '',
        '|数据|候选|相对 native 形状差异 % 范围|native 自身重复性最大 %|候选自身重复性最大 %|相对 native 共同 OK 覆盖最小 %|',
        '|---|---|---|---|---|---|']
    for s in summary:
        if s['dataset']=='MH01' or s['variant']=='native':continue
        range_text=(f"{float(s['normalized_shape_difference_min'])*100:.3f}–{float(s['normalized_shape_difference_max'])*100:.3f}" if s['normalized_shape_difference_min'] else '未完成')
        own=[float(x['normalized_rms']) for x in pairs if x['dataset']==s['dataset'] and x['kind']=='within_'+s['variant'] and x['status']=='FINISHED']
        own_text=f'{max(own)*100:.3f}' if own else '未完成'
        lines.append(f"|{label(s['dataset'])}|{s['variant']}|{range_text}|{float(s['native_repeatability_max'])*100:.3f}|{own_text}|"+
            (f"{float(s['common_ok_coverage_min'])*100:.2f}" if s['common_ok_coverage_min'] else '未完成')+'|')
    lines+=['', '2 项 L1/20:06:48 的自身重复性比较因共同 OK 帧不足而失败，保留失败，不填 0。',
        'V0/18:49:29 的形状差异范围落在 native 自身重复性范围内；V0/20:06:48 的上界超过 native 自身上界，不能统一称为“无可测差异”。',
        'L4/L2/L1 的低公共覆盖使局部形状差异不能代表全程稳定性；L4/20:06:48 相对 native 形状差异上界约 19.22%，自身重复性上界约 19.58%。',
        '', '## 失败现场','', '|数据|配置|序号|已完成帧|分类|现场路径|','|---|---|---|---|---|---|']
    for f in failures:
        lines.append('|'+ '|'.join([label(f['dataset']),f['variant'],f['run'],str(f['completed_frames']),f['classification'],f['stack_path'] or '原始输入错误日志'])+'|')
    lines+=['','L8/20:06:48 五次均完成 145 帧后卡住（第 146 帧未完成，1 起算）；均在第 138 帧初始化。',
        '8 份线程栈、各线程 wchan/status 与 SIGINT 前保存时刻均已验收。主线程位于重定位路径，部分现场在 MLPnPsolver/Eigen，另一些在 PoseOptimization；后台线程在等待。',
        '这是 PC 可重复触发的后端路径问题证据；具体死循环/退化数值根因尚未证明，不能直接归因于 SVD、硬件或仅层数。算法、参数和随机种子未为跑通而修改。',
        '只读源码发现可疑控制流：MLPnPsolver.cpp:115 的迭代条件使用 OR；Refine 成功提前 return true 时未设置 bNoMore。Tracking.cc:3679 的外循环只有匹配成功或 bNoMore 才耗尽候选。',
        '因此存在“持续得到候选位姿但后续内点始终不足”的无界重试可能，与栈在求解器和位姿优化之间变化相符；现场没有变量/计数器证明此分支，暂列首要软件假设，不改后端、不宣称根因已证实。',
        '', '## ATE 汇总修正','',
        f"旧 report 按浮点时间戳完全相等筛 OK 帧，遇 SLAM double 秒转纳秒的舍入而漏掉轨迹行；实测最大偏差 {max(x['max_rounding_ns'] for x in ate_coverage)} ns。",
        '已从 runs 原始轨迹按最近唯一整数源时间戳关联（最大允许 1000 ns，远小于 50 ms 帧间隔），恢复源纳秒；只改分析副本，原始数据和旧 report 均保留。',
        '完全相同的上游重复轨迹行按原 evo 口径保留权重；同时间戳不同位姿会报错，不静默覆盖。',
        f"修正脚本和测试有版本记录；{len(ate_coverage)} 次有效 MH01 的 evo Sim3 与 NumPy 逐点交叉验证通过，最小真值区间覆盖率 {min(x['coverage'] for x in ate_coverage)*100:.2f}%，详情见 acceptance.json。",
        '', '## 层数决策建议','',
        '1 层明显不适合当前实拍数据；2 层在 18:49:29 频繁丢失并产生多地图。',
        '4 层是当前候选中两段实拍均 5/5 跑完全程的折中，但仍有丢失、地图碎片和明显重复性波动，不可称为 native 等价或稳定达标。',
        '8 层在 MH01 和 18:49:29 表现好，却在 20:06:48 五次卡住；目前不能冻结为正式方案。',
        '没有一档在两段实拍上都达到 native/V0 的无丢失表现；现有结果支持优先讨论 4 层折中或先定位 8 层的重定位问题，最终由用户决定。',
        '', '## 验收与停止点','',
        '90 槽位、原始帧诊断对齐、18 组中位/范围、29 个 ATE 文件和 8 份卡死现场检查通过；候选鲁棒性存在上述失败。',
        '51 项已验收 Linux 二进制/依赖哈希与链接关系复核通过；时间戳修正 3 项回归测试和编排 10 项测试通过。',
        '协调器 FINISHED_AWAIT_LAYER_DECISION；电源模式已恢复，防休眠请求已释放。本轮不补跑失败、不启动新实验，规范 v1.0 尚未更新。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    ledger=[]
    for r in results:
        ate=(f"{float(r['ate_rmse_m']):.6f} m" if r['ate_rmse_m'] else ('未完成' if r['dataset']=='MH01' else '无真值'))
        ledger.append(f"{label(r['dataset'])} {r['variant']} #{r['run_index']} | 跑完={r['status']=='FINISHED'} | ATE={ate} | 降频=不适用（PC未设降频验收）")
    (out/'run_summaries.txt').write_text('\n'.join(ledger)+'\n',encoding='utf-8',newline='\n')
    hashes={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in ['results.csv','summary_by_layers.csv','native_differences.csv','acceptance.json','REPORT.md','run_summaries.txt','runtime_revalidation.txt']}
    (out/'SHA256.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(report=str(out/'REPORT.md'),finished=audit['finished'],failures=len(failures),
        raw_rows=all_rows,ate_runs=len(ate_coverage),min_ate_coverage=min(x['coverage'] for x in ate_coverage)),ensure_ascii=False))


if __name__=='__main__':main()
