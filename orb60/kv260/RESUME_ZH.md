# KV260 当前结果与续跑入口

**最新手动流程（2026-11-03）：** 桌面“手动建图与定位”只提供“开始建图”“结束并保存”。结束后自动下发本轮停止时Atlas当前／最近更新的地图并持续定位；单地图检查不阻断此手动交接，多个地图不混合坐标。关闭面板仅隐藏，再次双击桌面入口可唤回。真实PL、DPU、相机标定、帧身份及稀疏／稠密地图一致性检查保留。入口、源码和使用方法见[主说明](README_ZH.md#正常操作手动建图与定位)。

用户保存的1389帧建图最终map1已重新封装并成功原生导入7015，包含257,656个彩色点。原建图多地图和跟踪稳定性失败记录未改写；随后67帧短测未初始化新图，正常恢复map1定位通路，该次定位零有效位姿如实保留，不宣称新图现场重定位通过。证据在 `build/kv260_system/manual_latest_20261103_a/`。下面历史录像及更早单板结果保留原范围。

**最新状态（2026-11-03）：当前为7015＋KV260两板，USB摄像头接KV260。7015 PL提取ORB，KV260 PS建图、DPU深度、PL反投影、PS融合、Mali显示；地图交接后7015 PS定位并输出彩色背景HDMI。用户当前接受5–10 FPS建图目标，已要求进入摄像头阶段，不继续追求旧的30 FPS指标。请先读 [摄像头当前记录](camera/README_ZH.md#2026-11-03-实际移动相机记录) 和 `orb60/build/kv260_system/TWO_BOARD_PROGRESS_20261103.json`。下文为更早的单板CPU历史结果。**

完整视频入口最新已重新从建图跑到定位并通过：2297帧、一张地图、272,779个RGB点，完整几何8.78 FPS；随后7015定位2273帧、2163帧有效、初始化后全部有效，27.80 FPS。桌面 **两板建图与彩色定位（视频）** 已更新为该轮验证的配置。801个证据文件已电脑复核，详见 `build/kv260_system/complete_chain_20261103_a/HOST_VERIFICATION.json`。摄像头现场重定位及物理直连仍待用户回来后测试，未标记整项目完成。

更新：2026-11-02。项目根 D:\pld，板端根 ~/kv260_orb_20261102。

## 当前已实板跑通

单块 KV260：PL 提取 ORB；PS 运行 ORB-SLAM3、原始 MiDaS Small FP32 CPU 深度和 RGB 点云融合；Mali GPU 显示两个独立地图窗口。用户已暂停更早的完整 ORB＋DPU 迁移目标，本轮不要求 DPU。

运行 runs/actual_pl_ps_cpu_gpu_600_20261102_b/ 已 COMPLETED，进程退出码 0。600 帧 SD 视频输入、474 帧有效位姿、CPU ORB 调用为 0；5 个真正创建的 SLAM 关键帧进入深度与融合，最终 44,021 个彩色点、1,066 个可靠稀疏点。板端与电脑独立重算均为 ACTUAL_KV260_PL_PS_CPU_MIDAS_RGB_MALI_PASS。

源帧号 128、228、321、422、516，对应关键帧 ID 3、13、20、31、41。并行实测深度 3.01–4.49 秒/帧，融合另需 0.42–7.59 秒。配置的 3 秒是输入时间上的最小选帧间隔，不是墙钟刷新保证。待处理队列最多两个关键帧；本次没有跳过项。不是实时相机帧率或公制精度验收，单目坐标保留相对尺度。

## 电脑证据

- 完整证据：orb60/build/kv260_system/board_actual_pl_ps_cpu_gpu_600_20261102/，含逐帧记录、RGB 缓存、局部点块、最终 PLY、GPU 截图和 SHA256.json。
- 压缩包：orb60/build/kv260_system/actual_pl_ps_cpu_gpu_600_20261102_evidence.tar.gz。
- 验收 JSON：证据中的 actual_pl_ps_cpu_gpu_600_20261102_b/CPU_CHAIN_VALIDATION.json。
- 最终 GPU 截图：同运行 final_gpu_v2/map_framebuffer.png、viewer.png、sparse_framebuffer.png。这是对刚完成计算结果的离线查看；实时运行截图另存 gpu_snapshot/。
- CPU 数值检查：orb60/build/kv260_system/ps_cpu_midas_2threads_20261102.json，20/20 通过，最大归一化 RMSE 1.356e-6。独立暖机中位数 1.667 秒，不能替代并行耗时。
- 旧保存 PL 特征回放及 DPU 检查均保留，不替代当前实际 PL 结果。

## 当前硬件与编译

ORB-only 完整 K26 顶层为 4PPC / 150 MHz。完整布线 WNS +0.342 ns、WHS +0.010 ns，0 失败端点、0 未约束内部端点、0 路由错误。LUT 42,232、FF 47,518、BRAM tile 72、DSP 44。报告在 orb60/build/kv260_system/orb_only_4ppc_150_20261102_a/，工程在 .work/vivado/orb_only_4ppc_150_20261102_a/kv260_orb_only.xpr。

已手动易失加载 platform_orb_only/kv260-orb-only.bit.bin 及 kv260-orb-only-v3.dtbo。HPM0 128 位 AFI reg14 必须为 0x200，早期错误覆盖层不可复用。XRT BO 分配及缓存同步通过；UIO 当前 uio4 图像核 0xA0000000、uio5 描述子核 0xA0010000。重启后需重新核对，入口不猜节点、不自动加载硬件，启动文件未修改。

实际 PL 三帧与冻结参考逐字节一致，记录 runs/actual_pl_smoke_20261102_c/SMOKE.json。Python 调用耗时不是纯硬件吞吐指标。

PS 为 build/bin/mono_kv260、build/lib/libORB_SLAM3.so。本轮按原始 CMake O2 规则重新编译 Tracking.cc、mono_kv260.cc 并链接，其他源文件和对象哈希不变。证据 runs/ps_keyframes_v3_bounded_20261102/state.json。临时编译 swap 已关闭删除，fstab 未修改。

## 复现与查看

板端源码 sources/orb60/kv260/，原生 SLAM 源码 slam/。CPU 环境 .venv_ps_cpu，GUI 环境 .venv_gui；模型 models/midas_ps_cpu_fp32.onnx。它们与旧 DPU 环境分开。

在核对并加载本轮平台、登录桌面后，从板端终端运行（输出目录必须全新）：

```bash
cd ~/kv260_orb_20261102/sources
export DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000
../.venv_ps_cpu/bin/python -m orb60.kv260.run_system \
  --config ../system_ps_cpu_actual_20261102.json \
  --video ../replay_300/video.mp4 --max-frames 600 \
  --output ../runs/NEW_ACTUAL_CPU_RUN
```

桌面编号重启后须重查。当前配置含 360 秒诊断退出；常驻显示时在新配置移除 gui_test_seconds。默认彩色和稀疏地图分别显示，硬件 GPU 必须通过核对。

仅打开完成的结果：
```bash
../.venv_gui/bin/python -m orb60.kv260.gui \
  --dense ../runs/actual_pl_ps_cpu_gpu_600_20261102_b/final_view_v2
```

源码入口：run_system.py 编排；runtime.py XRT/UIO 与 ORB 调度；ps/Kv260DepthKeyframes*.h 真实关键帧选择；cpu_depth.py 深度；dense_service.py 有界低频任务；dense_fusion.py 几何、RGB、局部点块及位姿修正；gui.py 和 gles2_view.py 显示。

## 保留的问题记录

初次实际链 a 的 GUI 解释器被 resolve 成系统 Python，已修正为保留虚拟环境路径。最终结果查看 v1 缺少查看器元数据，弹框阻塞，已停止；v2 补全真实地图、体素及观测字段后正常截图、退出。

v1 离线查看覆盖了旧共享 desktop_status.json。原文件不重造，失败日志保留。当前 GUI 按 metrics 文件名隔离状态；验收使用实时进程最终 gpu_display.json 及 CRC 校验的第 599 帧截图包，核对整数时间戳。板端与电脑重算通过，实际帧身份、GPU 及 CPU ORB 约束未放宽。

旧 DPU 量化门槛失败和硬件未验收状态保留；CPU 成功不代表 DPU 通过。此前授权的统一平台电脑任务单独保留，不重复启动。

SSH 密钥保存在忽略的本机目录，凭据不进入证据包。此前板端地址 fe80::2f1:8b3f:e0bf:b910%16，网卡编号可能变化。

