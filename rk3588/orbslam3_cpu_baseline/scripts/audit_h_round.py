"""Read-only H1/H2 acceptance audit and reproducible Chinese decision report.

Run with WSL Python: frozen shared-library paths must resolve in Linux.
Never launches SLAM, extraction, builds, or experiments; writes derived output only.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
import pathlib
import shutil
import statistics as st
import sys
import zipfile


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(dict.fromkeys(k for r in rows for k in r)), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def label(dataset):
    return 'MH01' if dataset == 'MH01' else ('Tello 18:49:29' if '184929' in dataset else 'Tello 20:06:48')


def fmt(row, field, multiplier=1, digits=2):
    values = [row.get(field + s, '') for s in ('_median', '_min', '_max')]
    if any(v == '' for v in values):
        return '不适用'
    values = [float(v) * multiplier for v in values]
    return ('{0:.{d}f} [{1:.{d}f}, {2:.{d}f}]').format(*values, d=digits)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batch-root', required=True, type=pathlib.Path)
    p.add_argument('--output', required=True, type=pathlib.Path)
    a = p.parse_args()
    batch, out = a.batch_root.resolve(), a.output.resolve()
    if out == batch or out == batch / 'report' or batch / 'runs' in out.parents:
        raise ValueError('Derived audit output must not replace original evidence')
    out.mkdir(parents=True, exist_ok=True)
    state = json.loads((batch / 'batch_state.json').read_text())
    manifest = json.loads((batch / 'configs/manifest.json').read_text())
    datasets = {d['name']: d for d in manifest['datasets']}
    report = batch / 'report'
    results, summaries = read(report / 'results.csv'), read(report / 'summary_by_layers.csv')
    assert len(results) == len(state['schedule']) == state['completed'] == 90
    assert len({(r['dataset'], r['variant'], r['run_index']) for r in results}) == 90
    assert state['failed_slots'] == 0
    assert collections.Counter((r['dataset'], r['variant']) for r in results) == collections.Counter({(d, v): 5 for d in datasets for v in manifest['plan']['variants']})
    frozen = []
    for path, expected in state['frozen_runtime_sha256'].items():
        actual = digest(pathlib.Path(path))
        frozen.append(dict(path=path, expected=expected, actual=actual, matches=expected == actual))
    save(out / 'frozen_hash_audit.csv', frozen)
    assert all(r['matches'] for r in frozen), 'Frozen runtime/config/manifest changed'
    print('Frozen runtime/config/manifest hashes verified:', len(frozen), flush=True)
    sys.path.insert(0, str(batch / 'source'))
    from golden_report_audited import frame_facts
    counts = {}
    for d in datasets:
        if d == 'MH01':
            continue
        grouped = collections.defaultdict(list)
        for r in read(batch / 'historical_selected' / d / 'golden.csv'):
            grouped[r['variant'], r['timestamp_ns'], r['role']].append(r)
        for r in read(batch / 'corpus' / d / 'stats.csv'):
            grouped[r['variant'], r['timestamp_ns'], r['role']].append(r)
        counts[d] = grouped
    raw_hashes, checks, selected_stats, recoveries = [], [], [], []
    ate_checks = []
    facts_root = out / 'per_run'
    facts_root.mkdir(exist_ok=True)
    for row in results:
        d = datasets[row['dataset']]
        raw = batch / 'runs' / row['folder']
        meta = json.loads((raw / 'run_metadata.json').read_text())
        assert row['status'] == meta['status'] == 'FINISHED' and int(meta['exit_code']) == 0
        assert meta['completed_frames'] == meta['expected_frames'] == d['full_frames']
        assert meta['observed_affinity'] == [0, 2, 4, 6]
        derived = facts_root / row['folder']
        derived.mkdir(exist_ok=True)
        facts = frame_facts(raw, d, row, derived)
        fields = ['initialization_frame', 'post_init_ok_fraction', 'loss_segments', 'maps', 'inliers_median', 'state_ok_fraction', 'feature_count_median', 'outside_gt_tail_frames', 'outside_gt_tail_lost_frames']
        for field in fields:
            if row.get(field, '') != '':
                assert math.isclose(float(row[field]), float(facts[field]), rel_tol=1e-12, abs_tol=1e-12), (row['folder'], field)
        features = read(raw / 'FeatureTimeStats.csv')
        states = read(raw / 'TrackingStates.csv')
        layers = collections.defaultdict(list)
        for r in read(raw / 'SelectedPoints.csv'):
            layers[r['timestamp_ns'], r['role']].append(r)
        normal, initial, grid_values = [], [], collections.defaultdict(list)
        for f in features:
            ls = layers[f['timestamp_ns'], f['role']]
            assert sum(int(r['selected']) for r in ls) == int(f['count'])
            zero = next(r for r in ls if r['level'] == '0')
            target = initial if f['role'] == '1' else normal
            target.append((int(zero['selected']), int(f['count'])))
            if row['dataset'] in counts and row['variant'] in ('L8', 'L4', 'L8_T2', 'L4_T2'):
                grid = counts[row['dataset']][row['variant'], f['timestamp_ns'], f['role']]
                assert len(grid) == len(ls) and sum(int(r['selected']) for r in grid) == int(f['count'])
                cells = sum(int(r['cell_cols']) * int(r['cell_rows']) for r in grid)
                empty = sum(int(r['empty_cells']) for r in grid)
                grid_values[f['role']].append(empty / cells)
        for role, values in [('0', normal), ('1', initial)]:
            selected_stats.append(dict(dataset=row['dataset'], variant=row['variant'], run_index=row['run_index'], role=role,
                frames=len(values), level0_selected_median=st.median(x[0] for x in values), all_selected_median=st.median(x[1] for x in values),
                total_budget=5000 if role == '1' else 1000, grid_empty_median=st.median(grid_values[role]) if grid_values[role] else '',
                empty_scope='actual pre-truncation grid' if grid_values[role] else 'not applicable: octree / MH01 not audited for grid'))
        reset_count = (raw / 'run.log').read_text(errors='replace').count('LM: Active map reset recieved')
        # A map ID reused after ResetActiveMap is NOT relocalization to an old map.
        losses = read(derived / 'loss_segments.csv')
        if row['dataset'] != 'MH01' and row['variant'] == 'L8' and '200648' in row['dataset']:
            for loss in losses:
                recovered = loss['recovered'] == 'True'
                after = int(loss['end_frame']) + 1
                reinit = any(s['state_after'] == '1' for s in states[int(loss['start_frame']):after])
                classification = 'still non-OK at sequence end' if not recovered else ('active-map reset/reinitialization' if reinit and reset_count else ('relocalized' if loss['actual_relocalization'] == 'True' else 'tracking recovered without confirmed relocalization'))
                recoveries.append(dict(run_index=row['run_index'], **loss, classification=classification, active_map_reset_log_count=reset_count))
        checks.append(dict(dataset=row['dataset'], variant=row['variant'], run_index=row['run_index'], completed_frames=len(features), exit_code=0, row_alignment='PASSED', counts='PASSED', active_map_reset_count=reset_count))
        if row['dataset'] == 'MH01':
            analysis = report / 'analysis' / row['folder']
            ate = json.loads((analysis / 'ate.json').read_text())
            err = read(analysis / 'ape_errors.csv')
            rmse = math.sqrt(st.mean(float(r['absolute_error_m']) ** 2 for r in err))
            with zipfile.ZipFile(analysis / 'ape.zip') as z:
                evo = json.loads(z.read('stats.json'))['rmse']
            assert abs(rmse - evo) < 1e-10 and abs(rmse - ate['numpy_rmse_m']) < 1e-10 and abs(rmse - float(row['ate_rmse_m'])) < 1e-10
            assert len(err) == ate['associated_poses']
            assert '-as' in json.loads((analysis / 'evo_command.json').read_text())
            ate_checks.append(dict(folder=row['folder'], evo_rmse_m=evo, numpy_rmse_m=ate['numpy_rmse_m'], recomputed_ape_rmse_m=rmse, associated_poses=len(err), status='PASSED'))
        for path in sorted(raw.iterdir()):
            if path.is_file():
                raw_hashes.append(dict(path=str(path.relative_to(batch)), bytes=path.stat().st_size, sha256=digest(path)))
    save(out / 'run_audit.csv', checks)
    save(out / 'raw_hash_manifest.csv', raw_hashes)
    save(out / 'ate_audit.csv', ate_checks)
    save(out / 'selected_per_run.csv', selected_stats)
    save(out / 'L8_recovery.csv', recoveries)
    selected_summary = []
    for key in sorted({(r['dataset'], r['variant'], r['role']) for r in selected_stats}):
        group = [r for r in selected_stats if (r['dataset'], r['variant'], r['role']) == key]
        s = dict(dataset=key[0], variant=key[1], role=key[2])
        for field in ('level0_selected_median', 'all_selected_median', 'grid_empty_median'):
            vals = [r[field] for r in group if r[field] != '']
            s[field + '_median'] = st.median(vals) if vals else ''
            s[field + '_min'] = min(vals) if vals else ''
            s[field + '_max'] = max(vals) if vals else ''
        selected_summary.append(s)
    save(out / 'selected_summary.csv', selected_summary)
    for s in summaries:
        group = [r for r in results if (r['dataset'], r['variant']) == (s['dataset'], s['variant'])]
        for field in ('initialization_frame', 'post_init_ok_fraction', 'loss_segments', 'maps', 'inliers_median', 'ate_rmse_m', 'state_ok_fraction'):
            values = [float(r[field]) for r in group if r[field] != '']
            if values:
                for suffix, value in [('_median', st.median(values)), ('_min', min(values)), ('_max', max(values))]:
                    assert math.isclose(value, float(s[field + suffix]), rel_tol=1e-12, abs_tol=1e-12)
    from finish_c import compare
    shape_audits = []
    for pair in read(report / 'native_differences.csv'):
        assert pair['status'] == 'FINISHED'
        actual = compare(report / 'analysis' / pair['left'], report / 'analysis' / pair['right'])
        for field in ('normalized_rms', 'input_coverage', 'common_ok_frames'):
            assert math.isclose(float(actual[field]), float(pair[field]), rel_tol=1e-10, abs_tol=1e-12)
        shape_audits.append(dict(left=pair['left'], right=pair['right'], status='PASSED', **actual))
    save(out / 'shape_audit.csv', shape_audits)
    old = batch.parent / 'G1_layers_resume_20261006_013559'
    input_counts = []
    for row in results:
        if row['variant'] not in ('native', 'V0'):
            continue
        previous = read(old / 'runs' / row['folder'] / 'FeatureTimeStats.csv')
        current = read(batch / 'runs' / row['folder'] / 'FeatureTimeStats.csv')
        n = min(len(previous), len(current))
        mismatches = sum(any(x[k] != y[k] for k in ('timestamp_ns', 'role', 'count')) for x,y in zip(previous,current))
        input_counts.append(dict(folder=row['folder'], common_frames=n, old_completed_frames=len(previous), new_completed_frames=len(current), timestamp_role_total_count_mismatches=mismatches,
            scope='counts and role only; not a fresh byte comparison of all keypoint/descriptor fields'))
    save(out / 'H1_input_count_comparison.csv', input_counts)
    for name in ('results.csv', 'summary_by_layers.csv', 'H1_previous_ranges.csv', 'H1_old_new_shapes.csv', 'H1_L8_frame145.csv', 'H2_selected_summary.csv', 'native_differences.csv'):
        shutil.copyfile(report / name, out / name)
    for name in ('diagnosis.json', 'fixed_acceptance.json', 'T2_acceptance.json', 'launch_acceptance.json', 'batch_state.json'):
        shutil.copyfile(batch / name, out / name)
    outside = [r for r in read(report / 'H1_previous_ranges.csv') if r['all_new_within_old_observed_range'] == 'False']
    text = ['# H1/H2 90次决策轮验收与结论', '', '平台：**x86 PC / WSL2**。Tello：**借用内参，未本机标定**。实拍轨迹仅比较归一化 Sim3 形状；不表示绝对精度或真实尺度。PC耗时不作RK3588或FPGA性能结论。', '',
        '## 验收', '', f'90/90全序列完成，90个退出码均为0；每组5次，无替换、无卡死。逐帧状态/特征/地图对齐、实际调用提取器次数、逐层点数总和检查通过；{len(frozen)}项冻结二进制/库/配置/清单SHA256一致；30次MH01的evo(-as)、NumPy与逐点APE重算一致。原始输出不修改，原始文件SHA256见raw_hash_manifest.csv。', '',
        '**H1控制流修复通过，严格的旧范围回归并非全部通过。**下列12个“数据集×配置×指标”有新值落在旧观察范围外，逐项保留；不是统计显著性结论，不能宣称完全等价。旧MH01 native仅4次有效。', '',
        '## H1诊断与恢复', '', '仅加计数器时：零基第145帧进入重定位，外循环30000轮，累计30442次PnP迭代；29987次已耗尽预算却在Refine成功返回时bNoMore仍为false。最小修复是在这个返回点同步 bNoMore=(mnIterations>=mRansacMaxIts)，未改阈值、预算、循环条件或种子。正式批次未打开诊断计数器；修复作用于所有配置。', '',
        '修复后L8/20:06:48五次均完成：零基137首次OK，142起非OK，142–244共103帧非OK，第245帧重新初始化成功；第145帧附近仍为RECENTLY_LOST，并未重定位成功。五次均有一次活动地图重置，且序列末尾还有55–57帧非OK。恢复细节见L8_recovery.csv。Atlas最终地图数为1不代表没有重置；地图ID可复用，不能仅凭相同ID说回到原地图。', '',
        '## 主结果：中位数 [最小, 最大]', '', '初始化帧为1起算；OK为首次初始化成功之后的帧比例，另在results.csv保留全序列OK比例。丢失段包括RECENTLY_LOST/LOST及随后的重新初始化段。', '',
        '|数据|配置|初始化帧|初始化后OK %|丢失段|最终地图数|ATE RMSE cm|OK帧内点中位数|', '|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        text.append('|{}|{}|{}|{}|{}|{}|{}|{}|'.format(label(s['dataset']), s['variant'], fmt(s,'initialization_frame',digits=0), fmt(s,'post_init_ok_fraction',100), fmt(s,'loss_segments',digits=0), fmt(s,'maps',digits=0), fmt(s,'ate_rmse_m',100,3), fmt(s,'inliers_median',digits=0)))
    text += ['', '## H1超出旧范围的项目', '', '|数据|配置|指标|旧中位数 [范围]|新中位数 [范围]|', '|---|---|---|---|---|']
    for r in outside:
        text.append('|{}|{}|{}|{:.8g} [{:.8g}, {:.8g}]|{:.8g} [{:.8g}, {:.8g}]|'.format(label(r['dataset']),r['variant'],r['metric'],*[float(r[k]) for k in ('old_median','old_min','old_max','new_median','new_min','new_max')]))
    text += ['', 'Tello native/V0的初始化帧、OK比例、丢失段及地图数保持一致，但内点中位数小幅增加。MH01还存在ATE/丢失次数变化。Tello native/V0在完整SLAM模式下未出现RECENTLY_LOST/LOST，按Tracking控制流不会执行此次修复的重定位路径，所以这些内点差异不能直接解释为修复改变了重定位算法。新逐层观测日志可能改变多线程调度，只是待证解释。H1_input_count_comparison.csv逐帧比对两轮共同帧的时间戳、提取器角色和点数，明确不冒充描述子逐字节复检。H1_old_new_shapes.csv保留100个跨轮轨迹比较；旧轮范围有限，不能据此断言统计等价。', '',
        '## 实际使用的特征点：两档分别统计', '', '先取每次运行的逐帧中位数，再报告5次中位数及范围。role0=正常预算1000，role1=初始化预算5000。native四叉树预算不是严格硬上限，略多于1000正常；网格候选不足不回填。空格为真正格子在全局截断前无有效候选的比例，native/V0采用四叉树，不适用。历史统计见批次historical_selected/；旧L8卡死数据只覆盖已完成帧，不能充作完整序列对照。', '',
        '|数据|配置|档位|原图层点数|全部层点数|空格 %|', '|---|---|---|---:|---:|---:|']
    for s in selected_summary:
        if s['dataset'] == 'MH01':
            continue
        text.append('|{}|{}|{}|{}|{}|{}|'.format(label(s['dataset']),s['variant'],'初始化5000' if s['role']=='1' else '正常1000',fmt(s,'level0_selected_median',digits=1),fmt(s,'all_selected_median',digits=1),fmt(s,'grid_empty_median',100)))
    text += ['', '## 轨迹形状与覆盖', '', '下表为所有25个native与候选组合的最大归一化RMS（无量纲），和最小全输入帧公共OK覆盖率。低覆盖不能宣布无可测差异；90%是保守报告筛选，不是精度阈值。即便形状在native重复范围内，初始化和丢失也必须单独评价。', '',
        '|数据|配置|候选最大差异|native自身最大重复差异|最小覆盖 %|判读|', '|---|---|---:|---:|---:|---|']
    for s in summaries:
        if s['dataset']=='MH01' or s['variant']=='native':
            continue
        sufficient=s['coverage_sufficient']=='True'
        within=float(s['normalized_shape_difference_max'])<=float(s['native_repeatability_max'])
        verdict='形状无可测差异（此覆盖范围）' if sufficient and within else ('公共覆盖不足' if not sufficient else '形状差异超出native观察范围')
        text.append('|{}|{}|{:.6f}|{:.6f}|{:.2f}|{}|'.format(label(s['dataset']),s['variant'],float(s['normalized_shape_difference_max']),float(s['native_repeatability_max']),100*float(s['common_ok_coverage_min']),verdict))
    text += ['', '## 层数决策建议（未冻结默认值）', '',
        'T2明显补足弱纹理格子的点数。18:49:29的L4+T2为4/5次无丢失（另一次OK96.53%、1段丢失），L8+T2为5/5次无丢失；不能只看L4+T2的OK中位数100%。20:06:48的L8+T2为1/5次无丢失，L4+T2为0/5次无丢失，未达到native的5/5无丢失水平。MH01两种T2候选的ATE中位数均处于本轮native观察范围内，但这不表示每次结果全在该范围内或统计等价。', '',
        '若优先跟踪稳定性，建议8层+T2：两段Tello的丢失表现和内点数更好；若优先减少前端资源，4层+T2可作为折中，但接受18:49:29偶发丢失、内点减少及形状差异略超出native重复范围。4层+T2在20:06:48初始化更早（110对140帧），且公共覆盖充分时形状在native观察范围内；8层+T2该段形状比较公共覆盖不足，不宣称完全等价。最终默认层数仍由用户决定，规范停在v0.95，不自动更新v1.0。', '',
        '## 4层与8层的数据容量（估算）', '',
        '按v0.95合同，960×720总金字塔像素：4层1,736,552，8层2,140,237；752×480：4层906,516，8层1,117,367。8层比4层约增加23.25%像素，并非翻倍。并发全部层的14行u8窗口容量：960×720为46,616/70,216字节；752×480为36,506/54,988字节。每层尺寸与可分离高斯等其他缓存口径见既有delivery/v095/pyramid_storage.csv。以上是容量估算，不是已综合BRAM、吞吐或加速结果。', '',
        '## 交付与复现', '',
        '只新增验收脚本、派生CSV、逐次检查与本报告；没有修改黄金模型、SLAM逻辑、候选参数或旧原始数据。本轮无新增实验，无板端操作。运行audit_h_round.py --batch-root <原批次路径> --output <独立验收目录>即可重建这些验收文件；原冻结脚本可重建主统计。先查看summary_by_layers.csv或本报告，需要详细原因时再查对应单次原始目录。']
    (out/'REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    acceptance=dict(status='AUDITED_AWAIT_USER_LAYER_DECISION',formal_slots=90,all_completed=True,failures=0,
        raw_frame_rows=sum(r['completed_frames'] for r in checks),frozen_hashes=len(frozen),ate_crosschecks=len(ate_checks),shape_pair_crosschecks=len(shape_audits),
        h1_control_flow='PASSED',h1_all_new_within_old_ranges=False,h1_outside_range_metrics=len(outside),
        h2_flow_and_observability='PASSED',tello_equals_native_robustness=False,platform='x86 PC / WSL2',
        tello_intrinsics='借用内参，未本机标定',performance_conclusions=False,default_layers='AWAIT_USER',spec_version='v0.95')
    (out/'acceptance.json').write_text(json.dumps(acceptance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'SHA256SUMS').write_text(''.join(digest(path)+'  '+str(path.relative_to(out))+'\n' for path in sorted(out.rglob('*')) if path.is_file() and path.name!='SHA256SUMS'),encoding='utf-8')
    print(json.dumps(acceptance,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
