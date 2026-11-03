"""Summarize actual artifacts; missing/failed stages stay visibly unverified."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .common import digest,save


def build(root):
    root=Path(root).resolve();out=root/'orb60/build/kv260'
    def read(name):
        path=out/name
        return json.loads(path.read_text()) if path.exists() else {'status':'NOT_RUN'}
    float_gate=read('float/float_gate.json');q=read('quantized/quantization_test.json');calib=read('quantized/quantization_calib.json')
    compile_report=read('compiled/compilation.json');cloud=read('cloud_reference/result.json');video=read('video_regression/acceptance.json')
    diagnostic=read('compiled_diagnostic/compilation.json');placement=read('compiled_diagnostic/placement.json')
    variant=read('quantized_reluk/quantization_test.json');quant_cloud=read('cloud_quantized/result.json')
    fast_float=read('fastdepth/float_gate.json');fast_q=read('fastdepth/quantized/quantization_test.json')
    fast_cle=read('fastdepth/quantized_cle/quantization_test.json');fast_compile=read('fastdepth/compiled/compilation.json')
    fast_nocorr=read('fastdepth/quantized_nocorr/quantization_test.json');terminal=read('fastdepth/terminal_quantization_diagnostic.json')
    fast_placement=read('fastdepth/compiled/placement.json');fast_cloud=read('fastdepth/cloud_reference/result.json');fast_quant_cloud=read('fastdepth/cloud_quantized/result.json')
    recipes=[]
    for name,value in [('native-static',q),('reluk-cle',variant)]:
        if value.get('frames'):
            recipes.append({'recipe':name,'status':value.get('status'),'frames':len(value['frames']),
                            'passed':sum(bool(f.get('passed')) for f in value['frames']),
                            'worst_nrmse':value.get('worst_nrmse'),'minimum_spearman':value.get('minimum_spearman')})
    xml=out/'tests.xml';tests={}
    if xml.exists():
        tree=ET.parse(xml).getroot()
        suites=list(tree.iter('testsuite'));tests={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
        tests['status']='PASS' if tests['tests'] and tests['failures']==tests['errors']==0 else 'FAILED'
    prepared=read('replay_inputs/preparation.json')
    report={'scope':'KV260 dense component, computer-only, no board connection or SLAM rerun',
            'float':float_gate.get('status'),'calibration':calib.get('status'),'quantized_reference':q.get('status'),
            'target_compilation':compile_report.get('status'),'host_replay':cloud,'tests':tests,'video_regression':video,
            'diagnostic_compilation':diagnostic,'diagnostic_placement':{k:placement.get(k) for k in ['status','dpu_subgraphs','convolutions','ps_operations','fingerprints','target_names','final_half_pixel_resize_lowered_into_dpu']},
            'quantization_recipes':recipes,'quantized_cloud':quant_cloud,
            'deployment_model':'BLOCKED_BY_QUANTIZATION_GATE' if q.get('status')=='QUANTIZATION_FAILED' else compile_report.get('status'),
            'hardware_inference':'NOT_RUN','hardware_fps':'NOT_MEASURED','orb_ps_slam_migration':'NEXT_STAGE',
            'historical_input_tensor_reproduction':prepared.get('historical_tensor_reproduction'),
            'historical_input_differences':len(prepared.get('input_differences',[])),
            'weight_sha256':float_gate.get('weight_sha256'),'profile':json.loads(Path(__file__).with_name('profile.json').read_text())}
    report['selected_experimental_candidate']='fastdepth' if fast_compile.get('compiler_exit_code')==0 else 'midas'
    report['fastdepth']={'float':fast_float.get('status'),'quantized_reference':fast_q.get('status'),'compile':fast_compile.get('status'),
                        'dpu_subgraphs':fast_placement.get('dpu_subgraphs'),'convolutions':fast_placement.get('convolutions'),
                        'ps_operations':fast_placement.get('ps_operations'),'reference_cloud':fast_cloud,'quantized_cloud':fast_quant_cloud,
                        'worst_nrmse':fast_q.get('worst_nrmse'),'minimum_spearman':fast_q.get('minimum_spearman'),
                        'cle_status':fast_cle.get('status'),'cle_worst_nrmse':fast_cle.get('worst_nrmse'),'cle_minimum_spearman':fast_cle.get('minimum_spearman')}
    report['fastdepth']['no_bias_correction']={k:fast_nocorr.get(k) for k in ['status','worst_nrmse','minimum_spearman']}
    report['fastdepth']['terminal_quantization_diagnostic']={k:terminal.get(k) for k in ['status','backend','fix_point','representable_depth_max','passed','worst_nrmse','minimum_spearman']}
    errors={name:r['error'] for name,r in [('calibration',calib),('quantized_reference',q),('compilation',compile_report)] if 'error' in r}
    report['errors']=errors;save(out/'validation.json',report)
    text=['# KV260 稠密链电脑验收','',
          '本轮没有连接 ACZ7015、RK3588 或 KV260，没有重新运行建图。电脑参考推理不等于硬件仿真。','',
          '用户随后允许更换模型，以彩色稠密点云效果及 DPU 适配为目标。当前建议实验候选为 **FastDepth**；MiDaS 保留作为对照。两者都没有通过原定 20 张 INT8 一致性门槛，未将任何实验模型标为可部署模型。','',
          '| 阶段 | 真实状态 |','|---|---|',
          '| 20 张浮点基准 | '+str(report['float'])+' |',
          '| Vitis AI 校准 | '+str(report['calibration'])+' |',
          '| 20 张 INT8 参考 | '+str(report['quantized_reference'])+' |',
          '| B4096 目标编译 | '+str(report['target_compilation'])+' |',
          '| B4096 诊断编译 | '+str(diagnostic.get('status'))+'，compiler exit='+str(diagnostic.get('compiler_exit_code'))+' |',
          '| 可部署模型 | '+str(report['deployment_model'])+' |',
          '| 真实关键帧电脑点云回放 | '+str(cloud.get('status'))+' |',
          '| 接口及旧几何/数值回归 | '+str(tests.get('status','NOT_RUN'))+'，'+str(tests.get('tests',0))+' 项 |',
          '| 旧视频准备回归 | '+str(video.get('status'))+' |',
          '| KV260 DPU 执行 / 帧率 | 未上板 / 未测量 |','']
    for m in cloud.get('maps',[]):
        text += ['地图 %s：%s 个选定关键帧，%s 个有效深度关键帧，%s 个融合关键帧，%s 个 RGB 点。'%(m['map_id'],cloud.get('selected_keyframes'),m.get('valid_depth_keyframes'),m.get('fused_keyframes'),m.get('points')),
                 '剔除记录：`'+json.dumps(m.get('skipped',[]),ensure_ascii=False)+'`。','']
    if float_gate.get('frames'):
        values=[v for r in float_gate['frames'] for v in r['results'].values()]
        text += ['浮点检查包括原权重 eager、重新导出 ONNX 和静态折叠 ONNX。最大绝对误差 %.9g，最大归一化 RMSE %.9g。四处 align_corners 与最终 half_pixel 均保留。'%(max(v['max_abs_error'] for v in values),max(v['normalized_rmse'] for v in values)),'']
    if q.get('worst_nrmse') is not None:
        text += ['INT8 最大 NRMSE：%.8g；最小 Spearman：%.8g。逐张门槛仍为 0.03 和 0.98，无事后对齐。'%(q['worst_nrmse'],q['minimum_spearman']),'']
    if recipes:
        text += ['| 校准方案 | 通过样本 | 最大 NRMSE | 最小 Spearman |','|---|---:|---:|---:|']
        text += ['| %s | %s/%s | %.6f | %.6f |'%(r['recipe'],r['passed'],r['frames'],r['worst_nrmse'],r['minimum_spearman']) for r in recipes]
        text += ['','两种方案均保留原权重、固定上采样语义，并通过转换浮点检查；INT8 精度未达标。不能因为能导出、能编译或能生成点云就标为通过。','']
    if placement.get('status')=='COMPILE_PLACEMENT_PASS':
        text += ['诊断模型实际分配为 %s 个 DPU 子图，%s 个卷积类算子，CPU 无卷积。PS 辅助运算为 data-fix、四个 align_corners upsample-fix 和 fix2float。编译器将最后一处 half_pixel 上采样降低为 DPU 算子，数值仍需真实板端验收。目标指纹：`%s`。'%(placement.get('dpu_subgraphs'),placement.get('convolutions'),','.join(placement.get('fingerprints',[]))),'']
    if quant_cloud.get('maps'):
        m=quant_cloud['maps'][0]
        text += ['未通过精度验收的 native-static 量化参考仍做了独立诊断回放：%s 个有效深度关键帧、%s 个融合关键帧、%s 个 RGB 点。与浮点参考差异见 `quantized_cloud_comparison.json`。该点云不作为验收通过结果。'%(m.get('valid_depth_keyframes'),m.get('fused_keyframes'),m.get('points')),'']
    if fast_cloud.get('maps') and fast_quant_cloud.get('maps'):
        fm=fast_cloud['maps'][0];fq=fast_quant_cloud['maps'][0]
        text += ['## FastDepth 候选对照','',
                 '| 项目 | MiDaS | FastDepth |','|---|---:|---:|',
                 '| 诊断编译 DPU 子图 | %s | %s |'%(placement.get('dpu_subgraphs'),fast_placement.get('dpu_subgraphs')),
                 '| 卷积类算子（含编译器降低） | %s | %s |'%(placement.get('convolutions'),fast_placement.get('convolutions')),
                 '| PS 神经网络上采样 | 4 | 0 |',
                 '| 浮点参考点云 | %s | %s |'%(cloud['maps'][0].get('points'),fm.get('points')),
                 '| INT8 参考点云 | %s | %s |'%(quant_cloud['maps'][0].get('points'),fq.get('points')),'',
                 'FastDepth 的 38 个卷积和五处近邻上采样全部进入一个 DPU 子图。PS 仍负责输入适配、深度取逆、赋色、筛选和融合。该编译成功说明结构可映射，不代表 KV260 硬件运行或数值通过。','',
                 'FastDepth 浮点：%s 个深度有效关键帧、%s 个融合关键帧。INT8 参考：%s 个深度有效关键帧、%s 个融合关键帧。覆盖比 MiDaS 少；预览仍有缺口和重影，未补造表面。'%(fm.get('valid_depth_keyframes'),fm.get('fused_keyframes'),fq.get('valid_depth_keyframes'),fq.get('fused_keyframes')),'',
                 '| FastDepth 校准方案 | 20 张通过数 | 最大 NRMSE | 最小 Spearman |','|---|---:|---:|---:|']
        for name,value in [('native',fast_q),('ReLUk/CLE',fast_cle),('关闭偏置校正',fast_nocorr)]:
            text += ['| %s | %s/20 | %.6f | %.6f |'%(name,sum(bool(f.get('passed')) for f in value.get('frames',[])),value.get('worst_nrmse',0),value.get('minimum_spearman',0))]
        text += ['','FastDepth 的量化误差针对其自身 FP32 参考计算，不与 MiDaS 输出强行对齐。NRMSE≤0.03、Spearman≥0.98 仍未通过；当前交付为实验候选，后续需要继续精度诊断或确定新的明确验收方案，不能直接记为成功部署。','']
        if terminal.get('status')=='DIAGNOSTIC_ONLY':
            text += ['误差定位：只对原 FP32 网络的最后输出做主机定点量化模拟，%s/20 张通过，最大 NRMSE %.6f；完整网络仍为 0/20。当前证据把排查重点指向内部权重/激活量化及校准。该实验不是完整量化模型或硬件执行，也没有用于替代验收。'%(terminal.get('passed'),terminal.get('worst_nrmse')),'']
    text += ['历史 RGB 文件已按保存清单核对。历史 RK 输入张量未复现数量：%s；本轮使用重新冻结的 RGB/NCHW float32 输入。历史点云差异见 `historical_cloud_comparison.json`，不能把该比较当成 INT8 或 DPU 精度验收。'%report['historical_input_differences'],'',
             'Windows FFmpeg 首次旋转夹具检查失败的记录已保留；独立 Linux FFmpeg 环境执行原测试通过，未修改旧验收标准。','']
    if errors:
        text += ['未通过阶段的真实原因：','']+[f'- {name}: `{error}`' for name,error in errors.items()]+['']
    text += ['MiDaS 原权重 SHA256：`'+str(report['weight_sha256'])+'`。FastDepth 原 ONNX SHA256：`'+str(fast_float.get('source_sha256'))+'`。','',
             '下一步先匹配板上系统、VART/XRT 和 DPU 指纹，再真实执行 20 张数值验收和完整点云回放。本轮不宣称 KV260 帧率、DPU 通过或整机实时。ORB 与 PS SLAM 移植属于下一轮，必须生成 ORB＋DPU 共存平台。','']
    (out/'VALIDATION.md').write_text('\n'.join(text),encoding='utf-8')
    tracked=[p for p in (root/'orb60/dense/kv260').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    tracked += [p for p in out.rglob('*.json') if 'handoff' not in p.parts and p.name not in {'SOURCE_AND_RESULTS_SHA256.json','package.json'}]
    save(out/'SOURCE_AND_RESULTS_SHA256.json',{str(p.relative_to(root)).replace('\\','/'):digest(p) for p in sorted(tracked)})
    print(json.dumps({k:v for k,v in report.items() if k not in {'host_replay','profile','video_regression','diagnostic_compilation','diagnostic_placement','quantized_cloud','fastdepth'}},ensure_ascii=False))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args();build(a.root)

if __name__=='__main__':main()
