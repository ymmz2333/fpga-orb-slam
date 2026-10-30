# 两阶段演示桥接

摄像头固定接 Zynq。第一阶段 Zynq 采集、解码、PL ORB，RK3588 用实际 FPGA
特征建图；第二阶段把地图安装在 SD 上，由同一个 Zynq 程序执行固定地图定位。
第一阶段 HDMI 仅显示相机和特征；第二阶段 HDMI 显示既有地图、当前相机和轨迹。
不使用深度模型、彩色稠密点云或 CPU ORB，不自动回放旧录像。

**当前交付状态：本机软件验证版，不是已完成上板验收的版本。**
Win64 原生 Zynq 程序、协议/状态/地图测试和 Qt 控件可验证。
SDK 兼容 ARM 编译器在本机缺失，RK 实际源码集成编译未执行；没有新 ARM ELF，
没有此次摄像头建图、独立定位或重启实测。原有 bitstream 保持原样。

## 目录和实现选择

- `zynq7015_demo/`：独立 PS C++ 工作副本；`UPSTREAM_SHA256.json` 记录原始输入。
  不改 `zynq7015_usb_slam_20261024/` 和冻结 vendor。
- `orb60/demo_bridge/`：Python RK 控制服务、地图打包器、RK C++ 适配代码、脚本和门禁。
- `orb60/viewer/demo_controls.py`：现有 Qt 上位机的可选控制栏。

采集、网络、PnP、地图安装和状态机选 PS/RK 软件；继续复用配对 HLS ORB、
AMD PS/AXI 和既有 HDMI RTL。不改 PL，不引入 DMA 或新显示硬件。

## 相机和地图身份

`config/camera_source.csv` 保存用户给出的完整 1280×720 标定。仅中心裁剪：
`crop_x=160,crop_y=0`，输出 960×720，fx/fy/d0..d4 不变，
`cx=533.5148113045461,cy=328.48060919803237`。不缩放，不预先去畸变。
RK 和 PS 都在原始特征匹配后按同一畸变模型使用几何坐标。

```powershell
. ./scripts/project_env.ps1
& $ProjectPython -m orb60.demo_bridge.calibration --output orb60/demo_bridge/config
```

生成的 `camera_orb.csv` SHA256：
`d65c01acc1ba7c28dc4072d3f28c9fbc4957b4267e821f5fe2a827c8dcfac25f`。
`camera_rk.yaml` 由同一数据生成，图像缩放固定为1。镜头焦距/对焦状态应与标定一致。

`.zmap` 的 XYZ、描述子、关键帧和观测来自当前 RK 建图；单独的 PLY 和 Atlas
不可直接替代。每个地图包包含 manifest、全部定位文件和相机参数。传输检查 SHA256，
原生地图有 CRC，安装先保存/回读/再次保存做完全一致验证，再发布 current 指针。
RK 内部 float32 内参必须与共享标定的 float32 表示一致，才允许恢复为规范的
float64 元数据；不能借此接受另一台相机或另一次裁剪。
容量为最多12000点/256关键帧，超出明确失败，不裁剪、不拼接不同地图。

## 接口和状态

| 端口 | 内容 |
|---|---|
| Zynq TCP5601 | 校验标定后发送灰度＋原始 PL payload；最多3帧未确认 |
| Zynq TCP5602 | status/start/finalize/relocalize/stop/abort |
| Zynq TCP5603 | 地图 manifest、文件、准备提交，独立于控制连接 |
| RK HTTP5610 | GET `/status`、POST `/command`，JSON action |
| RK TCP18765 | 当前建图会话的 ORBVIZ01 显示流 |

所有地址放实际部署配置中；`rk.example.json` 的地址只是示例。
自定义帧头64字节、小端、版本1、CRC32；字段详见 `protocol.py` 与 `bridge_wire.hpp`。
帧保留会话号、相机源帧号、单调采集纳秒时间戳和灰度CRC；64字节特征记录不重排。
RK ACK 必须在该帧实际 SLAM 处理后返回，END 必须排空确认。

控制动作：`start_mapping`、`finalize_and_localize`、`relocalize`、`stop`。
重复开始/收尾不会重建会话。没有实际 PL 预检、标定不一致或 RK 未握手时不启动。
状态从 WAITING/MAPPING 经 FINALIZING/INSTALLING 进入 LOCAL；定位连续30帧有效后
`ready_to_disconnect=true`，丢失定位立即取消就绪标志。网络断开不会自行选择旧地图。
本地地图替换和停止命令在帧边界同步；S1 的 `r` 只重新加载当前地图，不清图。

## 本机验证

在项目根目录运行：

```powershell
./orb60/demo_bridge/verify.ps1
# 修改C++后，显式传当前机器编译器或设置FPGA_NATIVE_CXX：
./orb60/demo_bridge/verify.ps1 -Compiler '<本机g++.exe>'
```

需要 Python 项目依赖，以及 Windows MinGW C++17。编译串行，保留1536MiB内存门槛。
在受限执行环境内，回环 TCP 也可能需授予测试进程本机网络权限。
结果见 `orb60/build/demo_bridge/verification.json` 和相邻日志。
测试覆盖原几何/映射/解码/缓冲所有权、Python↔C++协议、分包/错误CRC、历史三帧
灰度和物理特征字节、排空、地图本地格式往返、损坏地图保留旧指针、断线禁止回退、
上传时停止命令，以及上位机按钮/硬件预检失败。

协议测试可执行文件 `test-bridge.exe` 含显式合成相机/有效位姿夹具；它不是 Zynq
程序，不能把其结果或耗时当作硬件定位证据。生产 `zynq-demo` 没有合成/回放输入。

## 后续构建与上板入口

1. 配置本机 SDK2018.3 兼容 ARM Linux hard-float GCC7.3.1，放在
   `scripts/local_env.ps1` 的 `FPGA_ZYNQ_CXX`，不修改全局 PATH。不使用 WSL。
   `build_arm.py` 默认复用交接包已验签的 ARM NEON libturbojpeg3.2.0，可显式给库路径。
   `.cmd` profile 本身不包含编译器；当前 `arm/checks.json` 如实记录缺失状态。

   ```powershell
   & $ProjectPython -m orb60.demo_bridge.build_arm --compiler '<arm-linux-gnueabihf-g++.exe>'
   ```

2. 在 RK 可连接时，用其当前带 FPGA流水/遥测/最终导出功能的完整源码作为输入，
   `install_rk.py --source OLD --output NEW` 创建独立源码副本；不修改保留构建。
   使用既有依赖配置 CMake，串行构建 `mono_bridge`，输出 `BUILD/demo_bin/mono_bridge`。
   此步骤需实际 RK 源码和依赖，当前仅验证了 FeatureIO 增量适配，不宣称完成 RK 编译。

3. Zynq 新 release 需要 `bin/zynq-demo`、既有配套 `bin/s1-reset-bridge`、两份相机CSV、
   `run_zynq.sh` 和 SHA256SUMS。确认原服务已停止、配对 ORB+HDMI bitstream/UIO WC、
   UVC 模块正常后启动脚本。脚本不加载 PL、不覆盖 BOOT.BIN/内核/设备树、不恢复录像服务。
   自动启动钩子需与实际 SD 初始化顺序整合后再验收；当前不冒称 SD 重启已验证。

4. RK 复制配置生成文件和 Python 包，填写 `rk.local.json`，启动：

   ```bash
   python3 -m orb60.demo_bridge.controller --config orb60/demo_bridge/config/rk.local.json
   ```

5. 电脑运行：

   ```powershell
   ./orb60/demo_bridge/run_viewer.ps1 -Controller http://<RK地址>:5610
   ```

先点击“开始异构建图”。有足够平移视差、地图稳定后点击“结束建图并切换”。等待
实际本地位姿就绪提示再拔网线。第二阶段上位机清除当前RK画面/位姿并提示看HDMI，
不会把停止更新的RK轨迹当成Zynq实时定位。

实体板验收需补齐：新摄像头/PL真实请求，当前场景建图，地图安装，实际本地定位的
覆盖率和误差，断网/关闭RK后的运行，以及 SD 重启。记录实际FPS、尾延迟、序号缺口、
HDMI欠载/AXI计数和内存；本轮没有这些实测值。

## 2026-10-26：录像定位与 GPU 窗口部署

新证据在 `orb60/build/demo_bridge/merge_20261026/README_ZH.md` 和
`acceptance.json`。本轮为显式现成录像输入，不使用摄像头。真实 Zynq PL/PS 跑完
2273 帧、2048 帧有效，帧号/纳秒时间戳/特征数量对应黄金清单，HDMI 无欠载/AXI 错误。
稠密环境 140244 点仅参与显示；定位使用 2400 个满足当前支持门槛的稀疏点。
Map V2 将稠密文件纳入 SHA/CRC/容量及稀疏地图、标定关联校验，仍接受旧 Map V1。
该录像使用其原临时标定，不套用新 USB 摄像头内参。

RK 默认入口现使用 `egl_raster_view.py`：Mali GLES 在独立 EGL FBO 绘制，再由 Qt
普通窗口呈现像素。双窗口非黑屏、旋转、相同稀疏样式测试通过。只在显式设置
`ORB60_GUI_BACKEND=software` 时使用旧软件渲染，不会静默降级。
RK 桌面自启动保留；Zynq 新 release 为 `/opt/orb-demo/releases/demo_20261026_dense_v1`，
SD 原自启动服务、bitstream、内核、BOOT 未变。完整摄像头建图/稠密交接及重启、
拔网线测试没有被这次录像验收替代。
