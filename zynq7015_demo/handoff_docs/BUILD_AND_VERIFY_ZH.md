# 主机构建与核验

本交接保存现有源与已通过的产物。本次归档只重做哈希/清单核对，没有重跑编译、仿真、综合、布线或板测。原报告中的绝对路径、时间和进程号作为历史证据保留。

## 环境

- Windows x64；Python 3.11/3.12。PC 标定还需 NumPy，固定 OpenCV 4.13.0.92 wheel 已提供，Pillow 用于独立 JPEG 像素参考。
- Vivado 2018.3；SDK 2018.3 Linaro GCC 7.3.1，ARMv7 Cortex-A9 / NEON / hard-float。不要直接改用新版工具后沿用旧验收。
- 本机 C++ 编译器原为 MinGW GCC 14.2；--compiler 可以选择本机 g++.exe，但 scripts/jpeg_dependency.py 的 native gcc 路径也要一致。
- 固定 CMake 3.31.10、Ninja 1.13.2 和 libjpeg-turbo 3.2.0。上游源码在 vendor 内；离线压缩包在 dependencies/offline_packages/。
- 原隔离 profiles 在 C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin，本包 dependencies/toolchain_profiles/ 是原件参考。不得永久改全局 PATH，不依赖 WSL。SDK、Vivado、Python 实际安装路径由接手者配置。
- 一次一个编译进程。每次下一个本机编译/工具链子进程启动前可用 RAM 至少 1536MiB；不足时保留 DEFERRED_MEMORY 和对象，不结束其他程序。

建议解压到短路径（如 D:/zslam/）。Vivado 2018.3 的 Windows XSim 曾在长路径下发生 Tcl_Close 崩溃，仿真脚本虽用短名，接手者仍需控制上层路径长度。

## 路径调整

保留源码快照原样才能核对既有 ARM 关系。新机器先运行包根 verify_handoff.py，再在工作副本调整以下已知主机常量并重新构建：

| 位置 | 需确认的路径 |
|---|---|
| scripts/build_arm_2018.py、build_s1_controls_2018.py、build_uvc_2018.py | PROFILE、SDK/COMPILER_BIN/TOOLBIN |
| scripts/synth_pl_2018.py 及部分 Vivado/DT 脚本 | xilinx-2018.3.cmd profile |
| scripts/check.py / jpeg_dependency.py | MinGW 编译器、SDK GCC；不能只修改一个 |
| profile .cmd | settings64.bat、SDK bin 和 Python 可执行文件 |
| build_uvc_2018.py 的 --archive | 包内 dependencies/factory_source/ACZ7015_Linux_Factory_Source.tar.gz |

脚本缓存使用源码/工具 SHA。换路径、改配方或换工具被拒绝恢复时，应新建构建，不篡改旧检查清单；只有同一工作目录、输入完全未变且状态 DEFERRED_MEMORY 的构建可 --resume。已 PASS 的历史目录不能 --resume。

## 离线依赖与软件

`dependencies/offline_packages/` 的 SHA 已纳入包清单。依赖可从缓存恢复，无需重新获取不固定版本：

1. 解压 cmake-3.31.10-windows-x86_64.zip 到 source/build/tools/cmake/，保留压缩包内 cmake-3.31.10-windows-x86_64/bin/ 层级。
2. 解压 ninja-win.zip 到 source/build/tools/ninja/，应得到 ninja.exe。
3. 可选 PC 标定：将指定 OpenCV wheel 原样解压到 source/build/calibration_python/；tools/calibrate_usb_camera.py 会添加此局部路径，不装入 ARM 或全局 Python。另配置本机 NumPy。wheel 和该工具从前的 provenance 在包内 evidence 中保留。
4. libjpeg-turbo 源码已在 source/vendor/jpeg_turbo/。保留的 native/ARM 静态库和检查清单位于 source/build/jpeg_*；工具/签名不匹配时自动重新串行构建。

在 source/ 下执行（将 profile 换成已确认的本机路径）：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/check.py
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/build_arm_2018.py
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/build_s1_controls_2018.py
```

顺序必须是 Native 完整 PASS，再新 ARM 构建 PASS，再匹配源码打包；旧二进制不能配新源。ARM checks 中的 arm_execution=NOT_RUN 表示交叉构建本身没有执行 ARM，另有 evidence/archives/ 下板端自检证据。

PC 标定回归：`python tests/test_camera_calibration.py`（使用具备 NumPy 的 Python；OpenCV 从局部目录读取）。真正相机重标需要实拍样本和原质量门槛，不能用合成测试代替。

Linux CMake 是另一个源码入口，需显式传入 `ZSLAM_TURBOJPEG_INCLUDE`（vendor/jpeg_turbo/upstream/src）和目标平台 `ZSLAM_TURBOJPEG_LIBRARY`；`cmake --build ... -j1`，`ctest --test-dir ... --output-on-failure`。不可将 Windows native 静态库用于 ARM。

## UVC 与 PL

UVC 不是重编 SD Linux。先 `scripts/build_uvc_2018.py --phase objects --archive FACTORY_ARCHIVE`；在独立板端目录运行产出的 genksyms-stage/run.sh，取回结果后运行 versions；再运行板端 modpost-stage/run.sh，取回 metadata 后 final。后两步需要 --build/--results，同样指定 --archive。具体命令与阶段约束以脚本 argparse 为准。

必须保持原 .config、Module.symvers、vermagic 和已知 memops 导出 CRC 一致，最终全部导入 CRC 通过；不 force-insmod，不忽略符号。出厂归档 SHA 为 41e9c2edcf4844f625129437306dcda6f4f1abf279cb8a63d83234a3aee266b5。该包已随交接提供，SDK 安装文件未提供。

需要改变 RTL 时，先运行权威仿真：

```text
fpga-python.cmd scripts/simulate_video_2018.py --top tb_tmds
fpga-python.cmd scripts/simulate_video_2018.py --top tb_video
fpga-python.cmd scripts/simulate_video_2018.py --top tb_video_full
fpga-python.cmd scripts/simulate_video_2018.py --top tb_serializer
```

之后 `synth_pl_2018.py --mem2-slices --video2`、check_pl_contract.py、report_pl_2018.py、route_pl_2018.py RUN --allow-serdes-hold-fix、report_route_2018.py ROUTE、finalize_route_2018.py ACCEPTED_ROUTE。脚本自动寻找包内同名 retained handoff 子目录，也支持 synth 的 --handoff 参数。布局布线会消耗较多内存，本次整理不运行。

已验收布线证据：WNS +0.015ns、TNS 0、WHS +0.013ns、THS 0；66068 网全路由、0 错；Slice 11523/11550（99.77%）。内部时序/CDC/Gray skew 已通过；4 个 TMDS 外部串行边界单列，未虚构常规输出 delay 模型。资源已很紧，任何 RTL 改动均需完整重验，不能沿用旧报告。

包内未重新放入 1.57GB 原灰度录像；完整黄金回归需先核对 manifest.json 外部数据项。最新用户禁止 HDMI 播放录像，后续 RAW 回归只能离屏。历史 bench_usb_camera.sh 等会播放录像或恢复旧服务，**不得直接运行**；需另做符合相机专用要求的受控测试脚本。
