"""Snapshot source and completed evidence; exclude credentials and unfinished binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'orb60/build/kv260_system'


def create(output,ps_archive):
    files={}
    def tree(source,prefix):
        for path in sorted(source.rglob('*')):
            relative=path.relative_to(source)
            if path.is_file() and '__pycache__' not in relative.parts and path.suffix!='.pyc':files[prefix+'/'+relative.as_posix()]=path
    files[ps_archive.name]=ps_archive
    tree(ROOT/'orb60/kv260','source/orb60/kv260')
    for kernel in ('layer2','descriptor'):
        job=BUILD/f'hls_{kernel}_150_20261102';tree(job/'inputs','pl/'+kernel+'/inputs')
        for name in ('recipe.json','run.tcl','unit_pass.stamp'):files['pl/'+kernel+'/'+name]=job/name
        files['pl/'+kernel+'/ip_export.zip']=job/'project/solution1/impl/export.zip'
        files['pl/'+kernel+'/retained_input_manifest.json']=ROOT/f'orb60/build/handoff/zynq7015_20261022/fpga_baseline/{kernel}/source_manifest.json'
        if kernel=='descriptor':tree(job/'descriptor_vectors','pl/descriptor/descriptor_vectors')
        for folder in ('csim/report','syn/report','sim/report'):
            for path in (job/'project/solution1'/folder).glob('*'):
                if path.is_file():files['verification/hls/'+kernel+'/'+folder+'/'+path.name]=path
        axi=BUILD/('axi64_layer2_20261102' if kernel=='layer2' else 'axi64_descriptor_20261102_b')
        for name in ('status.json','result.json','config.json','rtl_manifest.json','runtime/python_runtime.json'):
            files['verification/axi64/'+kernel+'/'+name]=axi/name
    files['pl/register_map_64.json']=BUILD/'register_map_64.json'
    ooc=BUILD/'ooc_layer2_20261102'
    for name in ('status.json','routed.dcp','timing_summary.rpt','setup_paths.rpt','hold_paths.rpt','utilization.rpt','utilization_hierarchical.rpt','route_status.rpt','drc.rpt','check_timing.rpt'):
        files['verification/ooc_layer2/'+name]=ooc/name
    for name in ('VALIDATION.json','VALIDATION.md','host_tests.log','tool_inventory.txt','kv260_gui_preview_v3.png'):
        files['verification/'+name]=BUILD/name
    files['verification/board_native_build_before_disconnect.log']=BUILD/'ssh_jobs/1793596944899606900/output.log'
    files['verification/board_gui.log']=BUILD/'ssh_jobs/1793596967627129100/output.log'
    tree(BUILD/'replay_300','replay_300')
    tree(ROOT/'orb60/dense/kv260/midas_refine','depth_source/midas_refine')
    files['selected_depth/best.pth']=ROOT/'orb60/build/kv260/midas_refine/qat-e2e/best.pth'
    for name in ('TEST_RESULT.json','README.md','pointcloud_comparison.png'):
        files['selected_depth/'+name]=ROOT/'orb60/build/kv260/midas_refine/video_test'/name
    files['selected_depth/selection.json']=ROOT/'orb60/kv260/config/depth_model_selection.json'
    tree(BUILD/'depth_midas_qat/compiled','models')
    for name in ('ps_operator_policy.json','INITIAL_POLICY_FAILURE.json'):
        files['models/'+name]=BUILD/'depth_midas_qat'/name
    files['models/depth_model_selection.json']=ROOT/'orb60/kv260/config/depth_model_selection.json'
    files['models/source_quantized.xmodel']=BUILD/'depth_midas_qat/export/runtime/Scoped_0_int.xmodel'
    for name in ('export.json','compile_gate.json','reproduction.json','model_identity.json'):
        files['verification/selected_qat_export/'+name]=BUILD/'depth_midas_qat/export'/name
    tree(BUILD/'selected_qat_viewer','selected_qat_viewer')
    tree(BUILD/'qa_separate_dense','verification/separate_dense_gui')
    for name in ('dense_regression.log','ps_host_syntax.log','gpu_required_rejection.log','qa_separate_dense_console.log','depth_qat_compile_console.log','depth_qat_review_console.log'):
        files['verification/'+name]=BUILD/name
    tree(ROOT/'orb60/build/handoff/zynq7015_20261022/LICENSES','licenses')
    if output.exists():raise ValueError('Fresh archive required')
    required=[p for p in files.values() if not p.is_file()]
    if required:raise FileNotFoundError(required)
    manifest={}
    guide='''# KV260 ORB / PS 迁移阶段电脑交付包

先阅读 verification/VALIDATION.md 和 source/orb60/kv260/RESUME_ZH.md。

- kv260_ps_source_v2_20261102.tar.gz：独立 PS 工程、ORB-SLAM3 源码、单板 ORB/DPU/RGB 编排、GPU GUI 和 ARM64 wheels。解压后运行 `bash sources/orb60/kv260/ps/build.sh slam build`。板端旧编译完成状态未知，续跑前先查进程，再同步 v2 源码。
- pl/layer2 和 pl/descriptor：K26 HLS C++ 源码、固定宏、目标和导出 IP。不是 .app 文件；源码在 inputs/FPGA_ORB_HLS/fastv2/next/src/。
- verification/ooc_layer2/routed.dcp：可在 Vivado 中 Open Checkpoint 查看独立图像核布局布线。不是 ORB＋DPU 完整顶层工程。
- verification：C/RTL 协同仿真、随机 64 位 AXI、资源时序与实际板端界面回放证据。图中历史 FPS 不是 KV260 性能。
- replay_300：真实录像和已保存 PL 特征的配对数据；准备完板端编译后用于 PS 建图回放，不会在 CPU 上重新提取 ORB。
- source：本轮作者源码、驱动接口、构建、打包和续跑说明。重新生成整份上游补丁树需要原 D:/pld 工作区；本包已生成的 slam 源码可直接独立编译。
- selected_depth：用户接受视觉效果的 MiDaS QAT 权重与对比报告。models/ 包含其已编译的 B4096 组件 xmodel、算子分区和模型绑定 PS 策略。99 个卷积均在 7 个 DPU 子图中，PS 执行插值/量化边界和显式核对的 4 个 ReLU。原数值失败保留，DPU 尚未上板验证。
- selected_qat_viewer：可直接由 GUI 打开的 165,761 点彩色结果；默认主面板、彩色点云、稀疏地图分别显示。verification/separate_dense_gui 为电脑软件渲染测试截图，正式运行拒绝软件渲染器。

单板入口为 `python -m orb60.kv260.run_system --config system.json --camera-device 0 --output runs/new_run`。必须先完成统一平台，并填写实际 UIO 地址及真实预检文件；程序不会自动加载 bitstream。

最终单板 ORB＋DPU 硬件、PS 最终建图回放及 HDMI/Mali 验收仍待继续。源码包不含 SSH 私钥、密码或占位硬件产物。本 v2 替代早期 ORB/PS 整理包。
'''
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as archive:
        for name,path in sorted(files.items()):
            data=path.read_bytes();manifest[name]=hashlib.sha256(data).hexdigest()
            archive.writestr(name,data,compress_type=zipfile.ZIP_STORED if path.suffix in ('.gz','.whl','.zip') else zipfile.ZIP_DEFLATED)
        archive.writestr('README.md',guide)
        manifest['README.md']=hashlib.sha256(guide.encode()).hexdigest()
        archive.writestr('SHA256.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP CRC failed')
        for name,digest in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('ZIP SHA mismatch '+name)
    receipt={'archive':str(output),'bytes':output.stat().st_size,'files_hashed':len(manifest),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'crc_and_entry_hashes':'PASS'}
    output.with_suffix('.verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--ps-archive',type=Path,required=True);a=p.parse_args();create(a.output,a.ps_archive)
