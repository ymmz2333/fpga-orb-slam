# KV260 单板 ORB、PS 建图与显示

已增加[开机与桌面启动模块](startup/README_ZH.md)：平台初始化、Ubuntu自动登录、手动面板和最新地图定位按顺序启动。建图仍由用户手动开始及结束；显示设置关闭息屏、锁屏与休眠。开机记录按实际boot ID保存，不复用重启前的硬件检查回执。

**两板单网线换接：** 尚未开始建图时，可保持两板供电，将KV260与7015各自连接路由器的线拔下，改为一根线直连两板。面板在断线期间显示“等待两板网络”，接通后自动恢复最新地图定位，再点击“开始建图”即可。无需电脑转发、路由器或重新获取IP；7015地址仍为`fe80::20a:35ff:fe00:122%eth0`（从KV260访问）。断线前后的流分段记录，缺失期间不生成虚假位姿。开始建图后应保持两板网线连接。

## 正常操作：手动建图与定位

KV260桌面入口为 **手动建图与定位**。控制按钮为 **开始建图、结束并保存**，另有“隐藏面板”。已有地图时，打开入口自动恢复持续定位；没有地图时等待用户开始建图。建图不按预设帧数结束。

点击“开始建图”后，先等待词典加载和状态变为“建图中”，再缓慢平移摄像头。点击“结束并保存”后，程序处理完已采集的在途帧，完成地图优化、DPU深度及点云融合的收尾，再自动下发本轮最近更新的地图并启动7015持续定位，无需再次点击。若Atlas产生多张地图，使用停止后导出的当前地图（`Atlas::GetCurrentMap()`），不按地图编号或点数大小选择、不拼接不同地图的坐标。单地图检查不再阻断这个手动入口，原本的多地图和丢失记录仍保存。关闭或隐藏面板不停止定位；再次双击桌面入口会唤回原面板。定位中点击“开始建图”会先安全交还摄像头和PL资源，再开始新建图。

没有初始化出新地图时会明确提示，保留并恢复原有地图定位。新地图仍受真实PL、DPU、相机标定、帧身份及稀疏地图和彩色点云一致性检查约束；原始性能验收失败记录不会改成通过。正常入口与此前固定帧数的自动验收脚本分开，下面的历史视频速度和摄像头测试记录保留其原测试范围。维护命令`quit`仅供受控更新和测试，不显示为正常操作按钮；意外断线仍记录为故障。

手动控制源码为 `manual_control.py`、`manual_gui.py`、`run_manual_session.sh`；相机安全结束入口由 `ps/build_manual_camera_entry.py` 生成，仍链接保留的建图库。7015明确停止协议在 `zynq7015_demo/src/network_camera.cpp`；它只在显式手动模式启用。每轮操作、地图、轨迹和错误保存在板端项目根的 `manual_sessions/manual_*/`，后续启动优先选择 `manual_latest_map.json` 指向的最后一次可用地图。

**最新摄像头固定地图定位已实板通过：2400帧、2386帧有效，初始化后99.50%，7015原生入口23.56 FPS，CPU ORB为0，HDMI无错误。** 摄像头接KV260，7015 PL提取ORB、7015 PS定位，显示333,261点固定彩色背景与实时轨迹；此定位阶段不执行DPU深度推理。新证据见 `build/kv260_system/camera_relocalization_20261103_a/HOST_VERIFICATION.json`。用户已确认可以换线，接下来从KV260桌面完成两板物理单网线运行；尚未把准备检查认定为直连验收。下段保留此次地图生成与早期未对准时的原结果。

2026-11-03最新输入已改为KV260直连USB 3.0彩色摄像头。实际移动相机1200帧已生成一张map0和333,261个RGB点，59个选中关键帧由DPU实际推理，包含收尾的几何吞吐7.77 FPS，Mali硬件显示。初始化后有效率93.82%，原稳定性检查保持未通过。地图已在7015原生导入并完成往返校验；后续摄像头画面转到未扫描区域，1200帧未定位，用户离场后要求跳过现场移动测试，故实景重定位暂缓验收。KV260桌面有 **摄像头建图与彩色点云** 和 **已有地图摄像头定位（联调）** 两个入口；后者直接使用此次地图。源码、命令及统计口径见 [摄像头入口](camera/README_ZH.md)。以下保存视频和旧单板结果保留原测试范围。

用户最新目标已改为 **7015＋KV260 两板**：7015负责ORB，KV260负责建图、DPU深度、融合和GPU显示，整段视频只生成一张地图，并导入7015 PS做固定地图定位；最终两板一根网线直连。当前以完整几何至少5 FPS为下限、10 FPS为优化目标，实际耗时仍记录。当前迁移进度、源码与验收入口见 [两板迁移说明](TWO_BOARD_MIGRATION_ZH.md)。下文单板CPU方案为保留的历史结果，不替代两板DPU目标。

最新完整视频入口已通过从头到尾的实板验证：2297帧本地视频只生成一张map0，2157帧有效，第140帧初始化后全部有效；58个关键帧实际DPU推理，PL反投影与PS融合生成272,779个彩色点，Mali硬件显示。处理段9.63 FPS，含最终几何收尾8.78 FPS。该轮新地图自动交接并在7015原生导入／往返后，完成2273帧固定地图定位，2163帧有效、初始化后全部有效，27.80 FPS。彩色背景构建1次复用2272次，HDMI无错误，CPU ORB为0。电脑独立核验801个证据文件，记录为 `build/kv260_system/complete_chain_20261103_a/HOST_VERIFICATION.json`。

KV260桌面 **两板建图与彩色定位（视频）** 已切换到上述通过的配置。摄像头建图和已有摄像头地图续测使用各自入口；路由器上的完整视频通过不代替真实相机现场重定位、物理单网线或重启验收。详细命令和板间地址见 [两板说明](TWO_BOARD_MIGRATION_ZH.md)。

7015最新固定视角显示版本已完成同地图/同视频2273帧复测：彩色背景只绘制一次，轨迹和当前位置实时更新；整段32.57 FPS，2135帧有效，HDMI无欠载或AXI错误。入口为 `/opt/orb-demo/kv260_migration_20261103_static_background/run_recording_localization.sh`。与前一版15.76 FPS的逐帧有效性/匹配一致；详见迁移说明及原始验证JSON。

以下单板CPU方案为2026-11-02保留的历史结果。单板运行入口为 `run_system.py`，深度后端必须明确选择；省略时仍使用原有 DPU 分支，不会自动切换 CPU。历史配置入口为 `config/system_ps_cpu.example.json`，不作为当前两板DPU验收配置。

2026-11-02：一块实际 KV260 已完成 600 帧 SD 视频输入测试，474 帧有效位姿，CPU ORB 调用为零；5 个真实 SLAM 关键帧进入 MiDaS，最终得到 44,021 个彩色点。实时窗口和最终结果窗口均确认使用 Mali-400 MP / GLES2。板端原始结果在 `~/kv260_orb_20261102/runs/actual_pl_ps_cpu_gpu_600_20261102_b/`，电脑证据在 `orb60/build/kv260_system/board_actual_pl_ps_cpu_gpu_600_20261102/`。

并行运行时，每个选中关键帧的深度推理为 3.01–4.49 秒，融合另需 0.42–7.59 秒，适合后台低频增量更新。`interval_seconds=3` 是输入视频时间上的最小选帧间隔，不保证每 3 秒完成一次稠密更新。待处理队列最多保留两个关键帧，过载跳过项会记录。此次验证不等于实时相机帧率或公制精度验收。

本轮使用完整 ORB-only K26 顶层：4PPC / 150 MHz，完成布线，WNS +0.342 ns、WHS +0.010 ns；实际 PL 三帧结果与冻结参考逐字节一致。MiDaS 为原始 Small FP32 模型，在 PS 上经 ONNX Runtime CPUExecutionProvider 执行，20/20 数值样本通过，未使用 DPU。FPGA 镜像通过易失配置加载，启动文件未修改，重启后须重新核对平台；入口不自动加载硬件。

单板职责：PL 的 ORB 核产生特征；PS 运行 ORB-SLAM3 跟踪、局部建图、回环及地图管理，并在独立后台进程执行低频深度和融合。主界面显示图像及特征，彩色与稀疏三维地图各使用独立 GPU 窗口。

## 源码入口

| 内容 | 入口 |
|---|---|
| PS 原生源码生成 | `prepare_ps.py` |
| PS 构建配置 | `ps/CMakeLists.txt`、`ps/build.sh` |
| PS 图形界面 | `gui.py`，复用 `../viewer/app.py` |
| 单板编排 | `run_system.py`、`config/system.example.json` |
| 彩色稠密链 | `frame_store.py`、`dense_service.py`、`dense_fusion.py` |
| PS CPU MiDaS | `cpu_depth.py`、`config/system_ps_cpu.example.json` |
| 真实关键帧选择 | `ps/Kv260DepthKeyframes*.h`、`ps/build_keyframe_adapter.py` |
| 原始结果验收与离线查看 | `verify_cpu_chain.py`、`prepare_cpu_result_view.py` |
| 模型绑定的 PS 辅助算子 | `depth/ps_ops/`、`depth/build_ps_ops.sh` |
| K26 HLS 配置与构建 | `pl/prepare_hls.py`、`pl/run_hls.ps1`、`pl/hls.tcl` |
| 64 位寄存器表生成 | `register_map.py` |
| XRT 缓冲与 ORB 双核调度 | `runtime.py` |
| 独立源码包 | `package_source.py` |

HLS 数值算法来自 `orb60/build/handoff/zynq7015_20261022/fpga_baseline/{layer2,descriptor}/inputs/` 的冻结发布源，复用前逐项验证发布哈希。新工程重新针对 **xck26-sfvc784-2LV-c** 生成，保留 4PPC、8 层、A32 方向和 BRIEF-256；使用 64 位 AXI 地址。新生成的寄存器偏移与旧 7015 不同，必须使用本次生成的头文件。

PS 建图使用独立生成的 ORB-SLAM3 源码，不依赖 RKNN、RK3588 或远端建图板。`mono_kv260` 只接受外部 ORB 特征，每帧检查 CPU ORB 调用数为零。图形显示由 ORB Studio 独立进程承担；核心库移除 Pangolin 渲染依赖，保留完整建图计算和异步只读遥测。显示可以降低刷新率而不丢建图输入。

## PS 编译

电脑在项目根执行（输出目录必须是新目录）：

```powershell
.venv/Scripts/python.exe -m orb60.kv260.prepare_ps --output orb60/build/kv260_system/ps_source_NEW
```

将独立源码包部署到 KV260 用户目录后：

```bash
bash sources/orb60/kv260/ps/build.sh slam build
```

默认单线程构建，避免 4 GB 板卡上并行编译耗尽内存。产物为 `build/bin/mono_kv260` 和 `build/lib/libORB_SLAM3.so`。

本次完整 Release `-O2` 编译曾为较大的 G2oTypes/Optimizer 源文件准备临时 2 GiB swap，编译结束后已移除。重新完整构建时需先检查内存余量；已生成程序的运行不依赖该临时 swap。

2026-11-02 已完成 KV260 本机 ARM64 的 Release `-O2` 编译与链接，并用保存的真实 PL 特征通过 300 帧 PS 建图回放：CPU ORB 调用为 0，190 帧有效位姿，导出 17 个关键帧、496 个可靠地图点及 3043 条观测。记录在 `board_ps_native_20261102/` 和 `board_ps_replay_300_20261102/`；这是 PS 链验证，KV260 PL 的现场特征提取另行验收。

## 本机图形界面

GUI 使用独立 Python 3.10 虚拟环境和 ARM64 安装包。运行系统需有桌面会话；在 KV260 接 HDMI 显示器、登录 Ubuntu 后的终端中执行：

```bash
cd ~/kv260_orb_20261102/sources
../.venv_gui/bin/python -m orb60.kv260.gui --dense-live 127.0.0.1:18786
```

界面和点云服务均在本机。主窗口保留图像、特征和控制面板；彩色稠密地图、稀疏地图分别使用独立窗口。GPU 路径使用 GLES2 兼容着色器和缓存顶点缓冲，正式入口遇到 llvmpipe/softpipe 等软件渲染器会退出；`--allow-software-renderer-for-test` 仅用于明确标注的电脑测试。历史记录可通过 `--recording PATH` 或 `--dense PATH` 打开。

启动器会在板端 X11 显示器进入 DPMS 节能关闭时唤醒显示，不修改系统节能策略。保存特征的 PS 回放界面使用 `--telemetry PATH --saved-pl-replay`，会持续标注当前 KV260 PL 未运行；不要把保存结果的瞬时读数当作整机实时性能。

## 彩色稠密链

`run_system.py` 从同一帧生成工作灰度，将真实 PL 特征送给本机 `mono_kv260`。PS 只读记录真正创建的 SLAM 关键帧；选中后通过 ACK 保存该帧原始 RGB，按整数纳秒时间戳、源帧号及灰度 CRC 核对。`dense_service.py` 使用明确选择的 CPU 或 DPU 深度后端；PS 执行逆深度拟合、多视角筛选、RGB 赋色、体素融合。点块按地图与锚点隔离并保留原始局部坐标，最终使用优化位姿和共同地图点重新定位，再送给 GPU 窗口。

保留的 DPU 方案包含 7 个 DPU 子图、99 个卷积，全部卷积位于 DPU。PS 算子清单除插值/量化边界外，显式审批了这份模型的 4 个 ReLU；审批策略绑定模型哈希。原始精度失败记录保留，用户视觉接受另列。此前 165,761 点显示属于保存结果的 GPU 测试，不能作为 DPU 推理通过的证据；本轮 44,021 点则由本机 PL＋PS CPU 新计算得到。

正式单板入口：

```bash
python -m orb60.kv260.run_system --config system.json --camera-device 0 --output runs/new_run
```

CPU 方案按 `config/system_ps_cpu.example.json` 填写；DPU 方案按 `config/system.example.json` 填写。示例寄存器地址保留为 null，须从实际已验证平台导出。CPU 方案使用 ORB-only 平台；DPU 方案需要 ORB＋DPU 统一平台。入口不猜地址、不自动加载 bitstream。SD 视频使用 `--video PATH`，保留视频 PTS 的整数纳秒时间。

## PL 与内存接入

器件、板卡定义和 IP 安装情况由 `pl/probe_tools.ps1` 读取。HLS 入口分别运行 C 仿真、综合、C/RTL 协同仿真并检查通过状态；这些单位结果不等于完整布局布线或上板通过。

`runtime.py` 采用 XRT BO 分配连续工作区，通过真实设备地址及显式缓存同步访问 DDR。UIO 仅映射经名称和地址核对的控制寄存器。运行前必须具备匹配平台和 ORB UIO 节点；现有 `axi-pmon` 节点不是 ORB 核，不能混用。驱动不自动加载硬件，超时后拒绝继续使用未复位的核心。

CPU 深度方案已使用 **ORB-only** 完整平台，不需要 DPU。更早的 ORB＋DPU 方案若继续，仍必须构建共存统一平台，不能交替加载两份 bitstream 来宣称同时运行。原有统一顶层任务保留，广义 DPU 迁移目标由用户暂停。入口和历史报告见 [统一平台](pl/UNIFIED_PLATFORM_ZH.md)，不作为本轮 CPU 链通过的前提。

板端现有 XRT 为 2.13.479，Python 为 3.10.12。官方 VAI 2.5 的目标 RPM 内 Python 模块对应 3.9，不能直接混装进 Ubuntu 22.04 的 Python 3.10 环境。本轮在板端从固定提交的官方源码构建 Python 3.10 运行库，独立安装到 `runtime_vai25/`，不替换系统库。入口为 `depth/build_board_runtime.sh PROJECT_ROOT FRESH_RUN_NAME`；源码包的 Git 元数据缺失由带哈希校验的构建补丁补齐，不修改网络算子。实际检查记录为 `orb60/build/kv260_system/DPU_BOARD_CHECK.json`，硬件推理仍需匹配平台及板端输出验收。

2026-11-02 原生 XIR、VART、GraphRunner 与所需五类 PS 插件的导入、ARM64 动态链接和加载检查已通过，完整库文件哈希在 `board_dpu_runtime_20261102/runtime_manifest.json`。构建保留了旧接口导致的失败记录；OpenSSL 3 诊断摘要接口适配通过 12 个原生摘要一致性检查。临时编译 swap 已关闭并移除。

`depth/ps_ops/` 提供官方库缺少的 float32 ReLU 插件，限制为选定模型的四个已审查节点，并导出模型哈希供 worker 核对。四处实际模型 PS 算子通过官方 CPU-only run_op 接口执行，294,912 个值与独立 PyTorch CPU 参考逐位一致。测试夹具仅缩短张量名称以适应文件名长度限制，部署 xmodel 未修改；这不是全模型 DPU 推理或精度通过的证据。源码入口为 `build_ps_ops.sh`，数值验证入口为 `ps_ops/make_golden.py` 与 `ps_ops/verify.py`。

私有运行库命令通过 `bash depth/runtime_exec.sh PROJECT_ROOT COMMAND ...` 启动，环境修改只对本次命令有效。原生 XIR 已在板上读取所选 xmodel 并核对完整子图、7 个 DPU 分区、99 个卷积及指纹，记录为 `board_dpu_runtime_20261102/native_model.json`；该检查不创建硬件 runner。构建依赖包括 `uuid-dev`，XRT 头文件需要它，不能将缺失头文件的 API 探测直接改为通过。

历史 DPU 只读预检使用私有解释器的 `python -m xdputil query`，强制 `XLNX_DISABLE_LOAD_XCLBIN=1`。当时基础平台未发现 XRT 设备，原失败记录保存在 `board_dpu_runtime_20261102/preflight.json`。本轮已手动加载 ORB-only 镜像及匹配设备树，XRT BO 分配、缓存同步和 UIO 访问已通过；这不使历史 DPU 预检或 DPU 推理自动通过。

保留 DPU 分支使用此前用户认可视觉效果的 **MiDaS Small QAT 微调版**，选择记录为 `config/depth_model_selection.json`，指纹 `0x101000016010407`；它与当前 CPU 分支的原始 FP32 ONNX 模型不同，不可混称。DPU 实际推理及同时运行仍未验收，原数值失败状态保留。

本轮验证结果和明确未通过项保存在 `orb60/build/kv260_system/`，以真实日志、退出码及报告为准。
