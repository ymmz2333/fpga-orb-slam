# Zynq 实时三维建图、定位与显示程序

本工程将现有 PL ORB 与新增的原生 C++ 建图、定位、软件 UI 连接成 Zynq PS/PL 应用。目标板 ACZ7015 / xc7z015clg485-2。2026-10-22 完成源码和轻量软件检查；2026-10-23 用户授权开始综合，并改为 Vivado 2018.3 工程。迁移入口、构建边界与结果判定见 [PL_BUILD_ZH.md](PL_BUILD_ZH.md)。

原 RK3588 的完整 ORB-SLAM3 和 UI 源码不在交接包中。本工程的建图、定位、地图管理和 UI 是新的实现，复用了交接包中已配对的 ORB Linux 引擎。它实现单目稀疏三维建图和重定位，未包含 ORB-SLAM3 的完整 Atlas、全局 Sim3 回环优化、视觉惯性融合或稠密重建。

数据路径：摄像头／GRAY8 回放 → PL ORB → PS 地图匹配与位姿优化 → 关键帧三角化／有限预算局部优化 → RGB565 UI → 显示接口。PC 回放模式直接读取物理 FPGA 的黄金特征，不做 CPU ORB。

| 目录 | 内容 |
| --- | --- |
| `src/math.cpp` | 有界小矩阵运算、八点本质矩阵 RANSAC、双视图恢复、三角化和稳健位姿优化 |
| `src/pnp.cpp` | 独立 P3P RANSAC 初值与内点优化；复用 OpenCV 4.2.0 的 BSD 数学子集，无 OpenCV 运行时 |
| `src/slam.cpp` | 新地图初始化、预测与投影匹配、关键帧补充、三角化、局部优化、丢失与重定位、地图容量限制 |
| `src/map_store.cpp` | CRC 保护的地图持久化、完整性校验、原交接地图导入 |
| `src/ports.cpp` | Linux V4L2、原始 GRAY8、摄像头回调、物理 UIO ORB、外部 DDR 输入、共享 UIO HDMI 双缓冲及 framebuffer 兼容后端 |
| `src/ui.cpp` | 1280×720 软件 UI：相机图像／特征、透视三维点云、相机视锥、轨迹、状态和耗时 |
| `interfaces/video_port.h` | 摄像头与显示回调的帧格式和缓冲所有权 ABI |
| `vendor/orb_engine/` | 未改写的原配对引擎与寄存器定义，来源和 SHA-256 在 `provenance.json` |
| `config/` | 冻结录像内参、明确标注的合成示例内参 |
| `tests/` | 几何、建图、跟踪、重定位、存取、坏数据、容量与外设所有权测试 |

Windows 轻量构建与测试，一次只启动一个编译进程：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/check.py
```

输出为 `build/native/zynq-slam.exe` 和 `build/native/checks.json`。默认使用 MinGW GCC 14.2.0、`-O0`，这是低开销功能检查，不是 ARM 性能构建。没有 OpenCV、Eigen、Qt、OpenGL 或 Python 运行时依赖；P3P 的 BSD 源码和再分发许可在 `vendor/opencv_p3p/`，打包时复制许可证。Windows 的原生 CAD profile 不提供 gcc，检查器通过 fpga-python profile 启动明确路径的 MinGW，并仅给该编译子进程设置 PATH。

在本目录下回放交接包的少量特征，从零建图：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/run.py --replay ../zynq7015_localization_handoff_20261022/zynq7015_localization_handoff_20261022/golden --frames 240 --max-points 3000 --max-keyframes 16 --output output/my_mapping --save output/my_mapping.zmap --snapshot
```

导入原地图进行定位：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/run.py --replay ../zynq7015_localization_handoff_20261022/zynq7015_localization_handoff_20261022/golden --import-map ../zynq7015_localization_handoff_20261022/zynq7015_localization_handoff_20261022/map --loc-only --skip 200 --frames 8 --output output/my_localization --snapshot
```

每次输出目录和保存的地图文件必须使用新名称，避免覆盖旧证据。回放可用 `--raw gray8.bin` 附加与处理帧顺序逐帧对应的紧密灰度图像；未附加时 UI 明确显示 FEATURE REPLAY，不伪造摄像头画面。

Linux 原生软件构建：

```sh
cmake -S . -B build/linux -DCMAKE_BUILD_TYPE=Release
cmake --build build/linux -j1
ctest --test-dir build/linux --output-on-failure
```

ARM 交叉构建已使用本机 SDK 2018.3 Linaro GCC 7.3.1 的 ARM Linux sysroot 完成，Linux V4L2、framebuffer、UIO 和 NEON 路径均参与编译。GCC 7 使用 Filesystem TS 兼容头并链接 stdc++fs。运行 `fpga-python.cmd scripts/build_arm_2018.py` 可在新目录独立重建，固定 profile 为 `zynq-arm-linux-2018.3.cmd`；O2、Cortex-A9、NEON、hard-float、pthread，C++/GCC 运行库静态链接，动态依赖 libc/libm/libpthread 和 ARM hard-float loader，最高 GLIBC 符号版本 2.17。编译通过与外设工作分别验收。

2026-10-23 已通过 SSH 在默认 SD 系统上运行 ARM 纯软件自测，全部通过。SD 启动、SSH、软件包、硬件配置边界和后续接入流程见 [SD_SSH_ZH.md](SD_SSH_ZH.md)。通用 CMake 交叉工具链文件仍为 `cmake/arm-linux.cmake`，需显式指定 hard-float GCC；通用 CMake 构建默认使用系统 C++ 运行库，其部署依赖由所选工具链决定。

已部署对应 PL、设备树及摄像头／显示驱动后，板端调用示例：

```sh
./zynq-slam --camera /dev/video0 --uio /dev/uio0 --fb /dev/fb0 \
  --calibration actual_camera.csv --output runs/live_001 --save maps/live_001.zmap
```

V4L2 输入要求原生 960×720 的 GRAY8 或 YUYV；程序不隐式缩放。本轮已合入 HDMI_2 1280×720p60 TMDS 输出，使用 `--hdmi-uio /dev/uio0` 与 ORB 共用同一个 WC UIO。也保留已配置 framebuffer 的兼容后端。应用自身不加载 PL；`scripts/load_hdmi_board.sh` 处理 RAM 加载和设备树绑定，SD 安装与 SSH 控制见 `SD_SSH_ZH.md`。原交接顶层与默认板上视频地址存在冲突，必须使用配对新 bit/设备树。

新摄像头必须提供真实标定。`camera_handoff.csv` 是原录像使用的借用内参，只供原数据回归；`camera_example.csv` 是合成测试示例，不能用于实际精度宣称。单目新地图保持相对尺度。

键盘控制为 `m` 建图、`l` 仅定位、`s` 保存当前地图的新版本、`r` 清空内存地图开始新建图、`q` 退出。在 Linux 终端的规范输入模式下按键后需回车。定位失败时 CSV 留空位姿，UI 显示 LOST，不重复上一帧位姿作为成功结果。当前图像核、描述子核和地图由一个应用拥有，不能同时启动旧网络服务访问 UIO。

默认容量为 12,000 个点、64 个关键帧、4,096 个轨迹样本；单帧最多 1,000 个特征。内存峰值不会随运行时间无限增长。关键帧、点槽和观测都有限额；旧引用通过槽代数失效。局部 BA 默认使用约 4 ms 的协作时间预算，并限制每批处理量；关键帧匹配及必要的三角化另外记录在 map_ms 中。调度抢占和一次计算自身耗时仍会影响真实帧时，不能把 BA 预算视为整帧硬实时保证。

30 FPS 是采集、ORB、建图／定位、渲染、提交显示的整机目标。`timing.csv` 分别记录各阶段耗时、33.33 ms 截止期超限和丢帧；`run.json` 将黄金特征回放与物理 ORB 模式分开，`hardware_acceptance` 保持应用级 NOT_VERIFIED，独立验收结论另存。PC 的特征回放帧率不包括 PL 提取，单张 UI 预览也不证明连续 HDMI 输出。新 HDMI_2 后端使用双缓冲和垂直消隐确认，拒绝扫描欠载或 AXI 错误；兼容 framebuffer 后端仍是直接拷贝。物理模式默认使用两个容量为 2 的队列，分开采集、ORB 与建图/绘图，`--serial` 可用于对比。流水线保持 FIFO 身份、不跳帧，异常传播并退出；CSV 中并行阶段耗时不应相加作为帧周期，另有 input_wait_ms 和 latency_ms。

地图保存后可用 `--load file.zmap --loc-only` 重定位，也可继续局部建图。保存包含相机、稀疏点、描述子、关键帧、观测与 CRC；加载失败不替换当前活动地图。它保存有限局部地图，不承诺无界场景的全局回环精度。

本次软件证据和 UI 预览在 `VALIDATION_ZH.md` 中记录。原交接包及现有 bit/ELF 不作修改。

2026-10-24 30FPS基线：最终HDMI PL布线WNS+0.015ns/WHS+0.013ns；完整2273帧物理ORB逐字节验证30.76FPS、2063有效、3000点/16KF、RSS12.74MiB，另用16MiB保留DDR窗口。两次SD重启自启及SSH控制已实测；含加载/保存/维护的连续三轮6819帧平均30.26FPS，最低整轮30.0066FPS，0丢帧/0欠载/0AXI错误。UI左右投影修正已生效。仍有帧时抖动，摄像头尚未实接，导入地图结果不能外推为任意新场景从零建图质量。详见[BOARD_ACCEPTANCE_ZH.md](BOARD_ACCEPTANCE_ZH.md)。该版保持为可恢复基线；60FPS在独立目录推进。
