# 提交源码与构建导航

## 1. 版本与目录

提交项目为 KV260＋ZYNQ-7015 两板系统。`main` 与 `submission-53996-20261104`
指向本次整理版本。保存的实板源码快照列于 `review/final_native_sources/`，
原有 50/50 实际编译输入覆盖记录在 `review/acceptance/effective_source_coverage.json`。
本次同步增加 `orb60/kv260/saved_map.py`，并更新控制器及其测试；该变化另在当前提交中可查。

## 2. ZYNQ-7015 PL：ORB 与 HDMI

- 图像核入口：`orb60/optimized/FPGA_ORB_HLS/fastv2/next/src/layer2_hls.cpp`。
  4PPC 通路由 `layer4_dataflow.hpp`、`layer4_images.hpp`、`layer4_io.hpp` 等组成。
- 描述子核：同目录 `descriptor_hls.cpp`；接口/缓存/方向矩定义在 `../include/`。
- 参考模型：`orb60/optimized/FPGA_ORB_SHARED_v1.0/`。
- HLS 导出与测试：`next/hls/`、`next/scripts/`、`orb60/scripts/hls.tcl`。
- 完整 ORB 系统 Tcl：`orb60/vivado/`。
- ORB＋HDMI 顶层：`zynq7015_demo/scripts/synth_pl_2018.py`，再按
  `route_pl_2018.py`、`report_route_2018.py`、`bit_pl_2018.py` 的顺序完成实现和导出。
- 视频 RTL 与引脚/CDC 约束：`zynq7015_demo/rtl/`。

现有 ZYNQ-7015 最终 HDMI 集成使用 Vivado 2018.3；较新的 ORB 开发/HLS 和
KV260 平台脚本使用 2024.2。不要把不同工具版本生成的 IP 缓存交叉覆盖。
按 `zynq7015_demo/PL_BUILD_ZH.md` 中的版本与门禁生成新工程；旧 `.xpr` 或 `.app`
不是源码入口。历史报告中的本机路径用于定位证据，迁移机器时通过
`scripts/project_env.ps1` 与本地覆盖设置工具路径。

## 3. ZYNQ-7015 PS：定位应用

主程序 `zynq7015_demo/src/demo_main.cpp`，匹配/PnP 为 `slam.cpp`、`pnp.cpp`，
地图读写为 `map_store.cpp`，显示为 `ui.cpp` 和 `display*`。
PL 引擎接口在 `vendor/orb_engine/`。该程序使用硬件 ORB，不以 CPU ORB 替代。

构建入口为 `zynq7015_demo/CMakeLists.txt` 和 `scripts/build_arm_2018.py`。
先用 `scripts/jpeg_dependency.py` 构建冻结的 libjpeg-turbo，再向 CMake 提供
`ZSLAM_TURBOJPEG_INCLUDE` 和 `ZSLAM_TURBOJPEG_LIBRARY`。ARM32 hard-float
工具链与 KV260 的 ARM64 编译器分开配置。具体部署参数见 `README_ZH.md`、
`SD_SSH_ZH.md`、`USB_CAMERA_30FPS_ZH.md`。

## 4. KV260 PS：建图与手动摄像头入口

`review/kv260_slam_base/` 包含完整的 PS SLAM 源树，
`orb60/kv260/ps/` 保留网络 ORB、ARM 优化、队列和摄像头入口生成/构建脚本。
`review/final_native_sources/network_bounded_published_mapper_20261103_b/source/`
是视频建图保留输入；`network_camera_manual_20261103_a/source/`
是手动摄像头入口。它们是增量编译输入，需结合基础 SLAM 树和构建脚本查看，
不是三份互相替代的完整 SLAM 实现。

在 Ubuntu 22.04 ARM64 上可先构建基础树：

```bash
bash orb60/kv260/ps/build.sh review/kv260_slam_base build/kv260_base
```

基础库编译后，使用 `build_network_adapter.py`、`compose_packed_mapper.py`、
`build_mapper_published.py`、`build_camera_entry.py`、`build_manual_camera_entry.py`
中保存的转换与编译流程生成对应入口。各阶段在新目录中生成 BUILD.json，
绑定源文件、已保留对象和库的哈希；不要把某一阶段命名相近的候选直接替换为发行版。
本次是源码提交，不包含板端已构建对象缓存。

控制器为 `manual_control.py`，界面为 `manual_gui.py`；`saved_map.py` 负责保存选择的
地图及恢复校验。`peer_link.py` 和 `run_7015_network_localization.py` 管理换线和重连。
`config/*.example.json` 提供参数结构，需按本机相机、网口、程序和启动回执配置。

## 5. KV260 PL/DPU 与 GPU

- DPU 深度 worker：`orb60/dense/kv260/worker.py`；当前选择 MiDaS Small QAT。
- 浮点、量化、重新编译与原数值结果：`orb60/dense/kv260/`、`midas_refine/`。
- 点投影 HLS：`orb60/kv260/point_pl/point_project.cpp`；独立 golden、协议测试和
  构建入口与源码放在同目录。
- 当前保留平台 Tcl：`review/kv260_hardware_source/system.tcl`；
  `orb60/kv260/point_pl/run_components.ps1` 和 `run_system.ps1` 是重新构建入口。
- AMD DPU IP 需按 `orb60/kv260/pl/prepare_unified_vendor.py` 和相关说明从官方版本准备，
  对应完整 KV260 K26 器件，而不是 Zynq-7000。
- GPU 显示：`gles2_view.py`；PS 融合：`dense_fusion.py`、`dense_service.py`、`voxel.py`。

现有部署使用原生 `xlnx_dpu` 内存分配/缓存同步和 UIO 点核控制。
配置/指纹核对失败时退出，不静默回退 CPU。硬件重建后重新核对 xmodel 指纹、地址和 ABI。
旧 XRT 分配器及独立 ORB＋DPU 候选作为历史保留，不作为本次平台入口。

## 6. 查看报告与执行电脑检查

KV260 完整布局布线资源、时序、路由报告在 `review/acceptance/kv260_*.rpt`；
对应 release/source manifest、实际板端验收 JSON 分别保留，日期和阶段不混写。
ZYNQ-7015 的报告生成入口在 `zynq7015_demo/scripts/report_*2018.py`。
完整原始报告按本地项目保留，GitHub 的证据摘要不代替所有原始日志。

```bash
python scripts/verify_submission.py
python -m pytest orb60/kv260/tests/test_manual_control.py -q
```

本次整理核对源码与压缩包，没有新运行综合、布局布线或板端实验。
