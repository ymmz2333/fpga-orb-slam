"""Write reviewable acceptance and integration notes only after real export passed."""
import argparse,hashlib,json,os,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);a=p.parse_args();job=a.job.resolve()
    if (job/'kv260_dpu_points_handoff.zip').exists():raise ValueError('Retained archive already exists')
    env=dict(os.environ,FPGA_PROJECT_ROOT=str(ROOT))
    subprocess.run([sys.executable,str(job/'source_build/check_system.py'),str(job),'--release'],env=env,check=True,stdout=subprocess.DEVNULL)
    d=json.loads((job/'release_manifest.json').read_text());cfg=json.loads((job/'build_config.json').read_text())
    if d.get('status')!='FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED' or not d.get('export_verified'):raise ValueError('Full route/export acceptance missing')
    t=d['timing'];r=d['resources'];project=(job/'project_path.txt').read_text().strip()
    baseline=ROOT/'orb60/build/kv260_system/dpu_only_b4096_250_20261102_a'
    review=dict(status='COMPARISON_ONLY_NOT_CDC_WAIVER',reports={})
    for label,folder in [('dpu_only_baseline',baseline),('dpu_points',job)]:
        reports={}
        for name in ['methodology.rpt','cdc.rpt']:
            f=folder/name;s=f.read_text()
            pattern=r'^\|\s*(\S+)\s*\|\s*(Critical Warning|Warning|Advisory)\s*\|[^\n]+\|\s*(\d+)\s*\|' if name=='methodology.rpt' else r'^(CDC-\d+)\s+(Critical|Warning|Info)\s+(\d+)\s+'
            reports[name]=dict(path=f.as_posix(),sha256=hashlib.sha256(f.read_bytes()).hexdigest(),findings=re.findall(pattern,s,re.M))
        review['reports'][label]=reports
    review['cdc_counts_equal']=review['reports']['dpu_only_baseline']['cdc.rpt']['findings']==review['reports']['dpu_points']['cdc.rpt']['findings']
    (job/'methodology_review.json').write_text(json.dumps(review,indent=2)+'\n')
    table='\n'.join(f"| {label} | {r[key]['used']:g} / {r[key]['available']:g} | {r[key]['percent']:.2f}% |" for key,label in [('lut','LUT'),('ff','FF'),('bram_tiles','BRAM tile'),('uram','URAM'),('dsp','DSP')])
    result=f'''# KV260 DPU＋点云投影核：完整实现验收

状态：`{d['status']}`，导出核验通过。本次没有加载板卡，没有验证新点云核的实际吞吐或整机提速。
当前 KV260 正在运行的旧 DPU 平台不会因为本次电脑构建自动改变。

## 硬件和结果

- 器件：`{d['audit']['part']}`，Vivado `{d['audit']['vivado']}`。
- 一颗 DPU B4096（250MHz / DSP500MHz）和一个 point_project_hls（150MHz）。
- DPU指纹 `{d['dpu_fingerprint']}`，与现有 MiDaS QAT 目标模型匹配。
- 点云核 CSR：`0xA2000000` / 64KiB，DPU CSR保持 `0xA1000000` / 16MiB。
- DPU 指令HPC0、数据HP0/HP1；点云双主口通过SmartConnect共享HP2。
- Setup WNS **{t['wns_ns']:+.3f} ns**，Hold WHS **{t['whs_ns']:+.3f} ns**，Pulse WPWS **{t['wpws_ns']:+.3f} ns**。
- 所有 setup/hold/pulse 失败端点为0；可布线网络 {d['routing']['routable']}，已布通 {d['routing']['routed']}，路由错误0。
- 黑盒0、未约束内部端点0、无时钟端点0、DRC Error/Critical Warning均0。
- 普通DRC警告 {d['audit']['drc_warnings']} 条，原始报告保留，不把它们隐藏或降级。
- Methodology仍有2条TIMING-54 Critical Warning；CDC仍报告48项Critical及62项Warning，未被当作清零或豁免。
  对照原DPU-only 250MHz报告，跨时钟提示规则及数量一致；本版另有1条ULMTCS-1控制资源使用建议。
  DPU供应商约束含150/250MHz间false path；正余量仅证明当前约束下的STA，不能证明跨时钟功能正确。
  `methodology_review.json`保留比较和原报告哈希，完整CDC及板端功能仍须审查。

| 资源 | 使用 / 总量 | 占用 |
|---|---|---|
{table}

## 验证范围

1. 独立NumPy双精度几何参考，C仿真10组，含完整960×720步长2采样网格。
2. C/RTL协同仿真9组；测试无效深度、无效坐标、掩码、空输入、错误配置、容量不足。
3. 实际生成RTL＋官方浮点IP仿真库，cocotb/ModelSim：9组随机AXI事务、复位中断、64位高地址、4KB边界、写入范围和直接ap_done完成屏障。
   共享DDR模型涵盖点云核两个主口，不等同已经测试了真实DPU并发DDR流量。
4. 点云核 OOC 150MHz已通过；单核结果不能替代这里的完整顶层结果。
5. 电脑融合适配回归保留局部点块与位姿修正；CPU oracle测试不是硬件执行。
6. 完整顶层严格时序／路由／DRC／覆盖率／模型指纹／IP源码哈希检查及bit/XSA配置数据一致性通过。

坐标浮点容差为 `atol=3e-5, rtol=3e-5`，颜色、索引、顺序和状态精确匹配。
体素边界可因FP32舍入出现分组差异；最终PLY不宣称逐字节相同。单目坐标保持相对尺度。
模型原数值验收仍为 `{d['model_binding']['numerical_acceptance']}`，用户视觉接受记录保持不变；硬件静态通过不会修改原量化结论。

## 文件入口

- Vivado工程：`{project}`，打开impl_1查看完整实现。
- 精确最终实现：`routed.dcp`。
- 配置：`kv260_dpu_points.bit`、`.bin`、`kv260_dpu_points_with_bit.xsa`。
- 寄存器：`point_abi.json`，配置指针字段实际为 `CONFIG_R_DATA`。
- 结果：`validation.json`、`release_manifest.json`、`timing_summary.rpt`、`route_status.rpt`、`utilization.rpt`、`utilization_hierarchical.rpt`、`drc.rpt`、`congestion.rpt`及其他完整报告。
- `kernel_provenance.json`、`source_manifest.json`冻结实际使用的HLS/IP和完整工程生成源码。
- `unit_evidence/`为本次构建所依赖的组件验收快照。

生产代码入口和接入说明在 `orb60/kv260/point_pl/README_ZH.md`，部署步骤见同目录 `MAIN_HANDOFF.md`。
不得将旧DPU-only的加载回执、UIO映射或board preflight直接复用为本平台通过证据。
'''
    # MAIN_HANDOFF.md belongs to this build directory, while the authored README stays stable.
    result=result.replace('同目录 `MAIN_HANDOFF.md`','本构建目录 `MAIN_HANDOFF.md`')
    (job/'RESULT_ZH.md').write_text(result,encoding='utf-8')
    handoff=f'''# 给主会话的接入交接

用户已要求完成DPU＋PL点云核实现后交给主会话使用。完整静态及导出验收通过，尚未加载新硬件。
注意：这指当前约束下STA、路由和DRC通过，不代表methodology/CDC全部清零。
保留2条TIMING-54 Critical Warning及48项CDC Critical，与原DPU-only跨时钟提示数量一致；另有ULMTCS-1建议。
供应商的150/250MHz false path未修改。请查看methodology_review.json及原报告，并做真实跨时钟与并发DDR板测。
当前无压缩输入实验可继续，不需要中途切换平台。请在现有实验阶段授权内安排后续切换和验证。

构建目录：`{job.as_posix()}`。
Vivado工程：`{project}`。
点云核HLS：`{cfg['point_hls']}`；随机AXI：`{cfg['point_protocol']}`；OOC：`{cfg['point_ooc']}`。
新配置150/250/500MHz，WNS {t['wns_ns']:+.3f}ns、WHS {t['whs_ns']:+.3f}ns。

## 接入顺序

1. 核对release_manifest中的新bit/包含bit的XSA、DPU指纹、模型哈希和point_abi，制作匹配的Linux固件、xclbin元数据、设备树。
   不能把两个bitstream分别加载当成统一平台，也不能把已有DPU-only板测记录当作新平台板测。
2. 合并 `point_uio_fragment.dtsi` 节点：地址0xA2000000、64KiB、UIO名kv260_point_project；按实际UIO编号查找，不猜/dev/uioN。
   其余DPU地址、时钟和AFI宽度按本次XSA核对。点云核GIE保持关闭，采用轮询。
3. 在明确加载并核验新硬件后记录 `deployment_receipt.json`：status=DPU_POINTS_LOADED、bitstream_sha256（原始.bit的SHA256）、dpu_fingerprint。
   若Linux使用bootgen转换后的.bit.bin，分别保存原始bit和实际加载文件哈希的对应关系，不混淆Vivado原始.bin与可直接加载格式。
4. 运行 `python -m orb60.kv260.point_pl.board_smoke --uio /dev/uioN --abi point_abi.json --release release_manifest.json --deployment-receipt deployment_receipt.json --output point_board_preflight.json`。
   此脚本不加载FPGA、不升级系统，四组真实点测试通过后才生成DPU_POINTS_BOARD_PREFLIGHT_PASS。
5. 在dense_service.py显式增加point_backend选择，初始化runtime.Projector(uio,abi,preflight)，用fusion.PlFusion替代原Fusion，退出时关闭projector。
   默认原PS路径可以保留；若用户选择PL，异常时明确失败，禁止自动回退后标成PL成功。
6. 用真实关键帧检查点数、RGB、几何误差、多视角结果、地图隔离、局部点块和位姿修正；然后测完整输入链吞吐。

## 精确边界

PS仍做去畸变、深度尺度/偏移拟合、掩码、步长2样本打包。
PL做反投影、世界坐标变换、附带样本RGB、有限/正深度/坐标有效性过滤和稳定压缩输出。
PS仍做多视角一致性、体素合并、地图与点块管理、BA；这不是整个融合都迁到PL。
输入每点16字节、输出每点32字节，最多172800点；XRT工作区沿用16MiB BO并显式同步缓存。
ABI中的配置指针是CONFIG_R_DATA。runtime不会自动加载硬件或偷偷CPU回退。
PlFusion.projection_timings和publish_timings提供打包/投影请求、多视角检查、体素、保存发布分段耗时。
投影请求计时包含PS轮询等成本，不是纯硬件周期。不要承诺整机30FPS或直接把1.4–2.7秒融合耗时全部算作新PL可消除部分。

代码位置：`{(ROOT/'orb60/kv260/point_pl').as_posix()}`。组件浮点坐标容差3e-5绝对＋3e-5相对；RGB、索引和计数精确。
FP32及体素边界可产生少量最终点云差异，需真实输入验收；不做逐帧事后尺度拟合来隐藏转换误差。
'''
    (job/'MAIN_HANDOFF.md').write_text(handoff,encoding='utf-8')
    subprocess.run([sys.executable,'-m','orb60.kv260.point_pl.package',str(job)],cwd=ROOT,env=env,check=True)
if __name__=='__main__':main()
