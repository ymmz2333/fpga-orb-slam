"""Build a separate refinement ledger without rewriting the main report."""
import json
import statistics
from pathlib import Path
from ..common import save,digest


def main():
    folder=Path('orb60/build/kv260/midas_refine');rows=[]
    for name in ['quantized','quantized_reluk']:
        file=folder.parent/name/'quantization_test.json'
        if file.exists():
            r=json.loads(file.read_text())
            rows.append({'case':'baseline-'+name,'status':r['status'],'passed':sum(f['passed'] for f in r['frames']),
                         'mean_nrmse':statistics.mean(f['normalized_rmse'] for f in r['frames']),
                         'worst_nrmse':r['worst_nrmse'],'minimum_spearman':r['minimum_spearman'],'precision':'INT8',
                         'report':str(file),'report_sha256':digest(file)})
    for file in sorted(folder.glob('*/*.json')):
        if file.name not in ['result.json','test.json']:continue
        r=json.loads(file.read_text())
        if 'worst_nrmse' in r:
            rows.append({'case':file.parent.name,'status':r['status'],'passed':r['passed'],
                         'mean_nrmse':statistics.mean(f['normalized_rmse'] for f in r['frames']),
                         'worst_nrmse':r['worst_nrmse'],'minimum_spearman':r['minimum_spearman'],
                         'precision':'INT16 diagnostic' if '16' in file.parent.name else 'INT8',
                         'report':str(file.relative_to(folder)),'report_sha256':digest(file)})
    save(folder/'summary.json',{'experiments':rows,'hardware_verified':False,'accepted_dpu_model':False})
    lines=['# MiDaS 独立量化优化实验','','原始 MiDaS 权重和主会话数据不被覆盖。所有实验保持原有双线性上采样语义。',
           '20 张冻结样本逐张验收：NRMSE ≤ 3%，Spearman ≥ 0.98；没有事后尺度/偏移对齐。','',
           '| 实验 | 精度 | 通过样本 | 平均 NRMSE | 最差 NRMSE | 最低 Spearman |','|---|---|---:|---:|---:|---:|']
    for r in rows:lines.append('| {case} | {precision} | {passed}/20 | {mean:.3f}% | {err:.3f}% | {minimum_spearman:.6f} |'.format(mean=100*r['mean_nrmse'],err=100*r['worst_nrmse'],**r))
    lines += ['','16 位扩大数值范围的结果只用于诊断，不能作为当前 DPUCZDX8G 的部署模型。',
              '单独增加位宽、维持旧范围且沿用 INT8 偏置校正的实验有耦合因素，不能据其好坏独立归因。',
              '扩充校准使用已保存的真实关键帧，排除所有验收样本的原视频帧编号；仍来自同一录像，不代表跨场景泛化验收。',
              '失败 API 探针和无效单位的中间统计已保留并标名；仅使用最终 saturation.json 的原始 bitwidth/fix_point 统计。',
              '未上板，未测量 DPU 性能；完整迁移状态以主会话另行维护的结果为准。']
    if any(r['case'].startswith('qat-e2e') for r in rows):
        lines += ['','端到端 QAT 使用 70 张训练、12 张内部验证及原 20 张冻结门槛样本。',
                  '本批包含初始 4 轮训练，以及从内部验证最佳权重开始、提高量化参数学习率的另一批 4 轮训练。',
                  'best.pth 是训练权重，不是可由 DPU 直接执行的模型。部署转换后的原 20 张门槛若不通过，则不进入目标编译或板端验收。']
    (folder/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    qat=[]
    for path in folder.glob('qat-e2e*/test.json'):
        r=json.loads(path.read_text())
        if r.get('frames'):
            score=min([e['selection_mean_nrmse'] for e in r['epochs']]+[r.get('initial_selection_mean_nrmse',float('inf'))])
            qat.append((score,path,r))
    if qat:
        _,path,r=min(qat,key=lambda item:(item[0],len(item[1].parent.name)))
        save(folder/'BEST_CANDIDATE.json',{'selection_rule':'lowest internal validation mean NRMSE; frozen 20-frame gate not used for weight selection',
             'weights':str(path.parent/'best.pth'),'weights_sha256':digest(path.parent/'best.pth'),
             'test_report':str(path),'test_report_sha256':digest(path),'numerical_status':r['status'],
             'hardware_verified':False,'dpu_deployable':False,'worst_nrmse':r['worst_nrmse'],
             'minimum_spearman':r['minimum_spearman'],'passed':r['passed']})
    files={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file() and p.suffix in ['.json','.pth','.py'] and p.name!='SHA256SUMS.json'}
    save(folder/'SHA256SUMS.json',files)

if __name__=='__main__':main()
