# KV260 + XC7Z015 联合视觉建图与彩色定位系统

2026-11-03 源码审阅快照。**当前版本是两块板协同：摄像头接 KV260，7015 PL 执行 ORB；KV260 PS 建图、DPU 推理深度、PL 反投影、PS 融合彩色点云、Mali 显示；保存后 7015 PS 在固定地图上定位，HDMI 显示彩色背景与轨迹。**

这是独立审阅分支 `kv260-7015-final-20261103`。仓库 `main` 中的 RK3588 方案作为历史参考；当前两板运行不需要 RK3588。KV260 的 ORB-only / ORB+DPU 候选平台也保留在源码中，不能把它们当成当前实际运行平台。

## 从这里开始审阅

| 范围 | 入口 |
|---|---|
| 手动操作与状态机 | `orb60/kv260/manual_gui.py`, `manual_control.py` |
| 手动重启与地图复用 | `manual_restart.py`, `install_camera_map_7015.py` |
| 开机自启动与当前启动预检 | `orb60/kv260/startup/` |
| 两板换线与断线恢复 | `peer_link.py`, `run_7015_network_localization.py` |
| 摄像头建图完整编排 | `run_camera_system.py`, `camera_input.py`, `camera/v4l2_capture.c` |
| KV260 原生 PS 建图 | `orb60/kv260/ps/`, `review/kv260_slam_base/` |
| 保留的实际编译输入 | `review/retained_native_mapping/`, `review/final_native_sources/` |
| 7015 ORB 特征服务 | `orb60/linux/`, `zynq7015_demo/vendor/orb_engine/` |
| 7015 PS 固定地图匹配 / 定位 | `zynq7015_demo/src/slam.cpp`, `pnp.cpp`, `demo_main.cpp` |
| 7015 彩色背景与轨迹显示 | `zynq7015_demo/src/ui.cpp`, `src/display*`, `rtl/` |
| DPU 执行及算子边界 | `orb60/dense/kv260/worker.py`, `orb60/kv260/depth/` |
| 关键帧选择 / 点云融合 | `orb60/kv260/dense_service.py`, `dense_fusion.py`, `voxel.py` |
| KV260 DPU + 点投影平台 | `orb60/kv260/point_pl/`, `review/kv260_hardware_source/` |
| GPU 3D 显示 | `orb60/kv260/gles2_view.py`, `gui_worker.py`, `orb60/viewer/` |
| 7015 HLS 与 HDMI 集成 | `orb60/optimized/FPGA_ORB_HLS/`, `zynq7015_demo/scripts/` |
| 上板与时序结果 | `review/acceptance/` |

## 正常操作

开机自动登录并显示面板。点击“开始建图”，缓慢平移摄像头；点击“结束并保存”，等待导出、下发后自动持续定位。采用停止时 Atlas 当前／最近更新的地图，不合并不同地图坐标。“重启程序”通过独立 user service 安全结束并重启应用；关闭面板仅隐藏。两板直连换线时等待网络恢复。

地图分两层：稀疏点及 ORB 观测用于几何定位；彩色稠密点云用于环境展示。7015 的彩色环境使用固定视角背景，轨迹更新；KV260 的建图显示使用 Mali GLES2。

## 本次变更与证据

- 修复 7015 存储满导致 `mktemp: No space left on device` 后前端无法启动的问题。
- 同一份已安装地图经版本、标定、二进制与文件清单验证后直接复用，重连不再复制一套地图。
- 加入空间预检与“重启程序”按钮，已保存独立的实际重启、DPU、Mali 检查证据。
- 与此版本相关的电脑测试为 416 项通过、4 项平台相关跳过；这些数字不代表本次 GitHub 发布重新进行综合或完整硬件验收。
- 完整 SD 视频链已有 2297 帧建图和后续 2273 帧定位记录；实际相机重定位另有 2400 帧记录。不同输入、不同地图与失败运行不能混用。
- 最新保存的 508,943 点地图保留在板上；本次板子暂不接电脑，未抓取该地图或声称同步了后续板端修改。源码来自电脑已保存版本，核心控制文件与上次实板快照哈希匹配。
- MiDaS 量化相对原浮点模型的原始门槛存在未通过项；后续使用经用户视觉接受的模型。不要将 DPU 执行成功等同原量化数值门槛通过。

## 审阅重点

请沿调用链检查：资源所有权和退出收尾；换线与断线恢复；最新地图选择和同图绑定；DPU/PS/PL 的实际边界；异常与真实失败记录；共享内存/缓存一致性；时间戳、帧身份和坐标一致性。不要仅依据旧 README 的历史段落推断当前运行版本。

当前运行依赖已配置的 ARM64 Ubuntu 22.04、VART/Vitis AI 2.5、原生 DPU 驱动及匹配的硬件资产。此分支以完整源码审阅为目的，未包含机器环境、SSH 私钥、账号密码、大型模型/视频、板卡系统镜像和 Vivado 缓存，也不声称任意机器一条命令即可复现。已有第三方 LICENSE/NOTICE 保持各自效力。

`SOURCE_SNAPSHOT_SHA256.json` 用于核对这次分支中的源文件。`review/acceptance/effective_source_coverage.json` 明确列出实际编译输入的本地取证覆盖情况；未找到的文件不伪造。
