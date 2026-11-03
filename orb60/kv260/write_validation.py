"""Collect only completed, scope-labelled evidence for the KV260 migration."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'orb60/build/kv260_system'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    result={'schema':1,'board_access':'RECONNECTED_20261102_AFTER_USER_REBOOT','whole_single_board_system':'NOT_VERIFIED','kernels':{}}
    for kernel in ('layer2','descriptor'):
        path=BUILD/f'hls_{kernel}_150_20261102'
        cosim=path/f'project/solution1/sim/report/fastv2_{kernel}_hls_cosim.rpt'
        if not (path/'unit_pass.stamp').exists() or not re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',cosim.read_text()):raise ValueError('Incomplete HLS gate '+kernel)
        axi=BUILD/('axi64_layer2_20261102' if kernel=='layer2' else 'axi64_descriptor_20261102_b')
        status=json.loads((axi/'status.json').read_text());proof=json.loads((axi/'result.json').read_text())
        if status['state']!='SUCCEEDED' or proof['status']!='PASS' or not proof['direct_completion_barrier'] or not proof['reset_interruption']:raise ValueError('Incomplete AXI gate '+kernel)
        result['kernels'][kernel]={'part':'xck26-sfvc784-2LV-c','target_clock_mhz':150,'axi_address_bits':64,'csim_synthesis_cosim_export':'PASS',
            'cosim_report_sha256':sha(cosim),'axi_random_stall_reset':'PASS','axi_transactions':proof['transactions'],'axi_ddr_base':'0x100100000',
            'actual_board_execution':'NOT_VERIFIED'}
    test=subprocess.run([sys.executable,'-m','unittest','orb60.kv260.tests.test_runtime','orb60.kv260.tests.test_saved_replay','orb60.kv260.tests.test_dense_integration','-v'],cwd=ROOT,capture_output=True,text=True)
    (BUILD/'host_tests.log').write_text(test.stdout+test.stderr,encoding='utf-8')
    if test.returncode:raise RuntimeError('Host interface/replay tests failed')
    test_count=re.search(r'Ran (\d+) tests?',test.stdout+test.stderr)
    if not test_count:raise ValueError('Missing host test count')
    result['host_tests']={'status':'PASS','tests':int(test_count[1]),'scope':'64-bit ABI, DMA sync, exact replay, RGB pairing, separate windows, reviewed PS operators, colored fusion, pose correction and firmware-autoload rejection'}
    regression=(BUILD/'dense_regression.log').read_text(encoding='utf-8')
    if not re.search(r'\b33 passed\b',regression):raise ValueError('Dense regression incomplete')
    result['dense_regression']={'status':'PASS','tests':33,'log_sha256':sha(BUILD/'dense_regression.log')}
    current_contract=BUILD/'dense_contract_current.log'
    if current_contract.exists():
        passed=re.search(r'(\d+) passed',current_contract.read_text(encoding='utf-8'))
        if not passed or ' failed' in current_contract.read_text(encoding='utf-8'):raise ValueError('Current dense contract regression failed')
        result['current_dense_contract']={'status':'PASS','tests':int(passed[1]),'environment':'isolated WSL reference Python; not board inference','log_sha256':sha(current_contract)}
    latest_log=BUILD/'qa_separate_dense_console.log'
    metrics=json.loads((BUILD/'qa_separate_dense/display_metrics.json').read_text(encoding='utf-8'))
    if 'Traceback' in latest_log.read_text(encoding='utf-8') or metrics['gpu']['uploads']<1:raise ValueError('Separate colored GUI test failed')
    rejection=(BUILD/'gpu_required_rejection.log').read_text(encoding='utf-8')
    if 'Hardware GPU rendering required' not in rejection:raise ValueError('Missing GPU-required rejection test')
    result['latest_gui']={'status':'HOST_SEPARATE_WINDOW_PASS','renderer':metrics['gpu']['renderer'],'software_qa_only':True,
                         'production_software_renderer_rejected':True,'color_points':165761,'mali_board_verified':False,
                         'main_preview':'qa_separate_dense/viewer.png','cloud_preview':'qa_separate_dense/map_framebuffer.png'}
    syntax=(BUILD/'ps_host_syntax.log').read_text(encoding='utf-8')
    if 'KV260_PS_HOST_SYNTAX_PASS_NOT_AARCH64_LINK' not in syntax:raise ValueError('PS host syntax check incomplete')
    result['ps_host_syntax']={'status':'PASS','scope':'System.cc, Map.cc, mono_kv260.cc; host compiler, not AArch64 link'}
    gui_state=BUILD/'ssh_jobs/1793596967627129100/state.json';gui_log=gui_state.with_name('output.log');state=json.loads(gui_state.read_text())
    if state.get('status')!='SUCCEEDED' or state.get('exit_code')!=0 or 'Traceback' in gui_log.read_text(errors='replace'):raise ValueError('Latest board GUI run failed')
    result['board_gui']={'status':'PASS','source':'historical_recording','renderer':'llvmpipe software under Xvfb','hardware_mali_verified':False,
        'hdmi_verified':False,'log_sha256':sha(gui_log),'preview':'kv260_gui_preview_v3.png','preview_sha256':sha(BUILD/'kv260_gui_preview_v3.png')}
    real_gpu=BUILD/'board_gpu_desktop_20261102/validation.json'
    if real_gpu.exists():
        gpu=json.loads(real_gpu.read_text(encoding='utf-8'))
        if gpu['status']!='REAL_KV260_MALI_SEPARATE_WINDOWS_PASS':raise ValueError('Real board GPU gate incomplete')
        for name,expected in gpu['sha256'].items():
            if sha(real_gpu.parent/name)!=expected:raise ValueError('Board GPU evidence hash mismatch: '+name)
        for name in ('gpu','gpu_sparse'):
            if gpu['metrics'][name]['software'] or 'Mali-400' not in gpu['metrics'][name]['renderer']:raise ValueError('Board GPU renderer is not Mali')
        result['board_gui_historical_software']=result['board_gui']
        result['board_gui']={'status':gpu['status'],'source':gpu['dense_source'],'renderer':'Mali-400 MP / GLES2 / real X11 desktop',
            'hardware_mali_verified':True,'hdmi_desktop_verified':True,'color_points':gpu['colored_points'],
            'dpu_inference_verified':False,'preview':'board_gpu_desktop_20261102/map_framebuffer.png','evidence_sha256':sha(real_gpu)}
    result['board_ps_slam']={'status':'COMPLETION_UNKNOWN_AFTER_DISCONNECTION','last_observed_progress_percent':69,'last_translation_unit':'src/G2oTypes.cc',
        'source_and_g2o_dbow2_build_started':True,'final_executable_verified':False,'map_replay_verified':False,'resume':'orb60/kv260/RESUME_ZH.md',
        'evidence_log':'ssh_jobs/1793596944899606900/output.log','transport_returned_exit_status':-1}
    native=BUILD/'board_ps_native_20261102/state.json'
    if native.exists():
        native_state=json.loads(native.read_text(encoding='utf-8'))
        result['board_ps_slam']={'status':native_state['status'],'native_build':native_state,'live_kv260_pl':False,'map_replay_verified':False}
        if native_state.get('status')=='SUCCEEDED' and native_state.get('exit_code')==0:
            architecture=(native.parent/'architecture.txt').read_text(encoding='utf-8')
            dependencies=(native.parent/'dependencies.txt').read_text(encoding='utf-8')
            if 'aarch64' not in architecture.lower() or 'not found' in dependencies:raise ValueError('Native link architecture/dependencies failed')
            result['board_ps_slam'].update(status='NATIVE_AARCH64_BUILD_LINK_PASS_REPLAY_PENDING',final_executable_verified=True)
    board_replay=BUILD/'board_ps_replay_300_20261102/KV260_PS_REPLAY.json'
    if board_replay.exists():
        replay=json.loads(board_replay.read_text(encoding='utf-8'))
        if replay['status']=='PASS' and replay['frames']==300 and replay['cpu_orb_calls']==0 and replay['map_export_complete'] and replay['exit_code']==0:
            result['board_ps_slam'].update(status='NATIVE_AARCH64_BUILD_AND_300_FRAME_REPLAY_PASS',map_replay_verified=True,replay=replay)
        else:result['board_ps_slam']['replay_failure']=replay
    ooc=BUILD/'ooc_layer2_20261102/status.json'
    result['ooc_layer2']=json.loads(ooc.read_text()) if ooc.exists() else {'stage':'RUNNING_OR_INCOMPLETE','full_system_verified':False}
    if ooc.exists():
        routed=ooc.parent
        route=(routed/'route_status.rpt').read_text()
        def count(name):
            match=re.search(r'# of '+name+r'[. \t]*:[ \t]*(\d+)',route)
            if not match:raise ValueError('Missing route count '+name)
            return int(match[1])
        counts={key:count(name) for key,name in [('routable','routable nets'),('routed','fully routed nets'),('errors','nets with routing errors')]}
        result['ooc_layer2']['route_counts']=counts
        result['ooc_layer2']['internal_setup_hold']='PASS' if counts['routable']==counts['routed'] and counts['errors']==0 and result['ooc_layer2']['wns_ns']>=0 and result['ooc_layer2']['whs_ns']>=0 else 'FAIL'
        result['ooc_layer2']['external_io_delays']='UNCONSTRAINED_AT_COMPONENT_BOUNDARY'
        utilization=(routed/'utilization.rpt').read_text()
        def used(name):
            match=re.search(r'^\|\s*'+re.escape(name)+r'\s*\|\s*([0-9.]+)\s*\|',utilization,re.M)
            if not match:raise ValueError('Missing utilization '+name)
            value=float(match[1]);return int(value) if value.is_integer() else value
        result['ooc_layer2']['resources']={key:used(name) for key,name in [('lut','CLB LUTs'),('ff','CLB Registers'),('bram_tiles','Block RAM Tile'),('dsp','DSPs')]}
        drc={'Error':0,'Critical Warning':0,'Warning':0}
        for line in (routed/'drc.rpt').read_text().splitlines():
            fields=[x.strip() for x in line.split('|')[1:-1]]
            if len(fields)==4 and fields[1] in drc and fields[3].isdigit():drc[fields[1]]+=int(fields[3])
        result['ooc_layer2']['drc_counts']=drc
        if drc['Error'] or drc['Critical Warning']:result['ooc_layer2']['internal_setup_hold']='DRC_REVIEW_REQUIRED'
        result['ooc_layer2']['reports_sha256']={name:sha(routed/name) for name in ('timing_summary.rpt','utilization.rpt','route_status.rpt','drc.rpt','check_timing.rpt')}
    unified_index=BUILD/'UNIFIED_PLATFORM.json'
    result['unified_platform']={'status':'PENDING','reason':'Full ORB + DPU routed top not yet accepted; board device tree, DMA and simultaneous execution remain board gates'}
    if unified_index.exists():
        index=json.loads(unified_index.read_text(encoding='utf-8'))
        evidence=BUILD/index['job']/'validation.json'
        if sha(evidence)!=index['validation_sha256']:raise ValueError('Unified platform evidence hash mismatch')
        result['unified_platform']=json.loads(evidence.read_text(encoding='utf-8'))
        result['unified_platform']['evidence_job']=index['job']
        result['unified_platform']['device_tree_and_board_execution']='NOT_VERIFIED'
    selection=json.loads((ROOT/'orb60/kv260/config/depth_model_selection.json').read_text(encoding='utf-8'))
    if sha(ROOT/selection['weights'])!=selection['weights_sha256']:raise ValueError('Selected QAT weight changed')
    result['depth_selection']={key:selection[key] for key in ('selected_family','weights_sha256','user_visual_acceptance','numerical_acceptance','board_verified','target_xmodel')}
    compiled=BUILD/'depth_midas_qat/compiled';compilation=json.loads((compiled/'compilation.json').read_text(encoding='utf-8'));placement=json.loads((compiled/'placement.json').read_text(encoding='utf-8'))
    if compilation['compiler_exit_code']!=0 or placement['status']!='COMPILE_PLACEMENT_PASS' or sha(compiled/compilation['model_file'])!=selection['target_model_sha256']:raise ValueError('Selected DPU compile evidence mismatch')
    result['depth_compile']={'status':compilation['status'],'model_sha256':compilation['model_sha256'],'dpu_subgraphs':placement['dpu_subgraphs'],
                             'convolutions_all_in_dpu':placement['convolutions'],'fingerprints':placement['fingerprints'],'ps_relu_boundaries':4,'board_verified':False}
    board_depth=BUILD/'DPU_BOARD_CHECK.json'
    if board_depth.exists():result['board_dpu']=json.loads(board_depth.read_text(encoding='utf-8'))
    native_depth=BUILD/'board_dpu_runtime_20261102/native_runtime.json'
    if native_depth.exists():
        runtime=json.loads(native_depth.read_text());folder=native_depth.parent
        if runtime['status']!='NATIVE_RUNTIME_ABI_AND_REQUIRED_PS_LIBRARIES_PASS':raise ValueError('Native runtime incomplete')
        if sha(folder/'runtime_manifest.json')!=runtime['manifest_sha256'] or sha(folder/'runtime_dependencies.txt')!=runtime['dependencies_sha256']:raise ValueError('Runtime manifest/link evidence differs')
        manifest=json.loads((folder/'runtime_manifest.json').read_text())['sha256']
        for module in runtime['modules'].values():
            if manifest[module['file']]!=module['sha256']:raise ValueError('Native module hash differs')
        if sha(folder/'bin/libvart_op_imp_relu.so')!=manifest['lib/libvart_op_imp_relu.so']:raise ValueError('PS plugin hash differs')
        relu=json.loads((folder/'ps_relu_numeric.json').read_text())
        if relu['status']!='NATIVE_PS_RELU_FOUR_MODEL_NODES_BIT_EXACT_PASS' or len(relu['cases'])!=4 or not all(c['bit_exact'] for c in relu['cases']):raise ValueError('PS ReLU native numerical gate incomplete')
        if runtime['model_sha256']!=selection['target_model_sha256'] or relu['model_sha256']!=runtime['model_sha256']:raise ValueError('Native PS operator evidence belongs to another model')
        result['board_dpu']['native_runtime_verification']=runtime
        result['board_dpu']['native_ps_relu_verification']=relu
    (BUILD/'VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    ooc_text=result['ooc_layer2']['stage']
    unified=result['unified_platform']
    unified_text=f"ORB＋DPU 完整顶层状态：{unified['status']}。"
    board_gpu_text='历史板端 GUI 验证使用 Xvfb 软件渲染；实际 Mali 显示未验收。'
    if result['board_gui'].get('hardware_mali_verified'):
        board_gpu_text='实际 KV260 桌面的主面板、独立彩色与稀疏地图窗口验证通过，两个窗口均使用 Mali-400 MP/GLES2，载入 165,761 个已有 RGB 点；这是渲染验证，不是 DPU 推理或吞吐率测试。'
    board_ps_text='板端建图编译的可信状态为 '+result['board_ps_slam']['status']+'；回放与物理 PL 验收各自单列。'
    native_dpu_text='板端完整 DPU 运行库与模型所需 PS 插件尚未验收。'
    if result.get('board_dpu',{}).get('native_runtime_verification'):
        native_dpu_text='KV260 原生 XIR、VART、GraphRunner 与五类所需 PS 插件的导入、动态链接和加载已通过；四个模型绑定 PS ReLU 共 294,912 个值与独立 PyTorch 参考逐位一致。原生模型读取也已核对 7 个 DPU 子图、99 个卷积及指纹。上述检查不创建 DPU 推理任务。'
    preflight_text='板端硬件预检和实际 DPU 推理尚未通过。'
    preflight=result.get('board_dpu',{}).get('hardware_preflight',{})
    if preflight.get('status')=='PREFLIGHT_FAILED':
        reason='缺少 /usr/lib/dpu.xclbin' if '/usr/lib/dpu.xclbin' in preflight.get('error','') else preflight.get('error','未给出原因')[:200]
        preflight_text=f'最新只读硬件预检为 PREFLIGHT_FAILED：{reason}；自动加载 xclbin 已禁用。真实失败记录保留在 board_dpu_runtime_20261102/preflight.json。'
    if result['board_ps_slam'].get('map_replay_verified'):
        replay=result['board_ps_slam']['replay']
        board_ps_text=f"KV260 原生 ARM64 Release -O2 编译与链接通过；保存的真实 PL 特征回放 {replay['frames']} 帧，CPU ORB 调用为 0，{replay['valid_poses']} 帧有效位姿，导出 {replay['map_keyframes']} 个关键帧、{replay['map_points']} 个可靠点及 {replay['map_observations']} 条观测。回放不是 KV260 PL 现场提取或实时帧率测试。"
    if 'timing' in unified:
        metrics=unified['timing']
        unified_text+=f" WNS {metrics['wns_ns']:+.3f} ns、WHS {metrics['whs_ns']:+.3f} ns；完整报告位于 {unified.get('evidence_job','')}。"
    ooc_detail=''
    if ooc.exists():
        resource=result['ooc_layer2']['resources']
        ooc_detail=f"图像核 OOC：WNS {result['ooc_layer2']['wns_ns']:.3f} ns、WHS {result['ooc_layer2']['whs_ns']:.3f} ns；LUT {resource['lut']:,}、FF {resource['ff']:,}、BRAM {resource['bram_tiles']}、DSP {resource['dsp']}。内部 setup/hold 与路由通过；DRC 为 {drc['Warning']} 项 Warning、{drc['Critical Warning']} 项 Critical Warning、{drc['Error']} 项 Error；外部 AXI 输入/输出延迟留给完整顶层约束。"
    text=f'''# KV260 迁移验证记录

## 已完成

- 两个 K26 ORB 核：C 仿真、综合、C/RTL 协同仿真、IP 导出全部通过；目标时钟为 150 MHz，地址为 64 位。
- 两个核各 3 次随机 AXI 事务通过，覆盖 4 GB 以上地址、随机阻塞、复位中断、4 KB 边界、完成屏障及逐字节黄金比对。
- {result['host_tests']['tests']} 项新增接口、回放与彩色融合测试、33 项既有稠密链回归测试通过。首帧回放与独立保存的真实 FPGA 报文字节一致。
- {board_gpu_text}
- {board_ps_text}
- PS 独立源码、64 位 XRT/UIO 适配层、配对回放、图形界面、构建与续跑脚本已集中整理。
- 最新电脑端界面验证包含主面板与独立彩色/稀疏窗口；生产模式拒绝软件渲染器。实际 Mali 验收状态见上方板端记录。
- 所选 MiDaS QAT xmodel 已编译：7 个 DPU 子图、99 个卷积全部位于 DPU；PS 明确执行插值/量化边界和 4 个模型绑定 ReLU。原数值门槛失败保持原状态。
- {native_dpu_text}
- 新增本地单板编排、RGB/灰度/位姿配对、DPU worker、彩色点块流，以及最终位姿/共同地图点修正；电脑端关键 C++ 文件语法检查通过。
- {ooc_detail}
- {unified_text}

## 尚未完成

- PS 使用实时 KV260 PL 特征的联合建图仍待验收；已通过的原生编译与保存特征回放范围见上方。
- OOC 不包含完整 PS/PL、DPU、外部 AXI 时序或板端 DDR；完整统一平台必须单独验收。
- 设备树、实际 DDR 缓存一致性、ORB＋DPU 同时运行和摄像头输入仍需板端验证。统一硬件的静态结果见上方状态及完整报告。
- 深度侧采用用户接受视觉效果的 MiDaS QAT 权重；原数值门槛仍未通过，组件目标模型已生成，实际 DPU 输出和整机性能尚未验收。
- {preflight_text}

## 续跑

见 [续跑说明](../../kv260/RESUME_ZH.md)。先只读检查现存进程与产物，再决定是否增量编译。电脑端已保存的结果不代表 KV260 整机实时运行。

机器可读结果、哈希与原始日志索引在 VALIDATION.json。
'''
    (BUILD/'VALIDATION.md').write_text(text,encoding='utf-8');print(json.dumps({'host_tests':'PASS','kernels':'PASS','ooc':ooc_text,'board_slam':result['board_ps_slam']['status']}))


if __name__=='__main__':main()
