# ACZ7015：150 MHz FPGA、网口和电脑 ORB-SLAM3 联调

2026-10-21。5000 点扩容按用户最新指示暂停；本次未更改 HLS、未重新布局布线，
使用原已签核的 960×720、8 层、1000 点预算、4PPC／150 MHz 版本。

## 已完成的实体链路

```text
电脑 WSL：真实录像灰度帧
    → 千兆 PS_ETH → Zynq Linux 接收与专用 DDR
    → PL 图像核／精确方向和 BRIEF 核
    → 千兆网返回原始特征 → 电脑 ORB-SLAM3 → 地图和轨迹
```

PL 继续采用已通过的自定义 HLS 和 AMD PS7／AXI／时钟 IP。
Linux 驱动、网络、调度和 SLAM 适配采用 PS／电脑软件。
这次没有修改 PL 的像素、选点、方向和 BRIEF 计算，也没有改变金字塔或 PL 输出顺序。

- FPGA Manager 运行时加载成功，bit SHA256：
  `b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60`。
- 实体器件 IDCODE `0x0373b093`；PS FCLK0 为 100 MHz，PL MMCM 输出 150 MHz。
- 两核 AXI-Lite 地址 `0x43c00000`、`0x43c10000`，均完成空闲状态检查。
- `/dev/uio0` 映射两个 64 KB 控制窗口和 `0x20000000` 起始的 16 MB DDR。
  该 DDR 位于实时设备树已有的 512 MB `reserved-memory/no-map` 内，不占用 Linux 普通内存。
- 使用三 raw／两 blur 槽和每层独立点缓冲区，方向描述子与下一层图像核重叠。
- 使用非缓存 UIO 映射、ARM DSB 屏障及核完成检查；不新增 DMA。
- 板端服务当前位于 `/tmp/orb60-150`，监听 TCP 5600。

旧 VDMA、音频及其时钟驱动在加载前按依赖顺序解绑，避免访问已替换的 PL。
没有覆盖 SD 的 `BOOT.BIN`、`system.bit`、`system.dtb`、`uEnv.txt`；重启仍进入原系统。
新增的 `/lib/firmware/orb60_150mhz.bin` 是供运行时管理器读取的文件。
当前配置不会在重启后自动重装，也未修复或依赖 JTAG 驱动。

## 实测结果

### 逐字节门禁

九帧交替运行普通图、压力图、空点图，数量分别为 280／942／0。
所有输出记录，包括坐标、顺序、方向矩、A32、角度及描述子，均与独立 Python golden
保存的结果逐字节一致。两种 SLAM 角色均经过测试。

| 实测阶段 | 最小 | 平均 | 最大 |
|---|---:|---:|---:|
| 输入已在 DDR 后的八层 PL 流水 | 4.950 ms | 5.300 ms | 5.879 ms |
| PS 输入复制到专用 DDR | 7.375 ms | 7.425 ms | 7.478 ms |
| 电脑请求图片到收到特征 | 29.208 ms | 33.310 ms | 39.691 ms |

这些是实体板测试，不沿用仿真周期换算。第一行包含 PS 配置／观察核完成的开销，
不是网络端到端帧率，也不是精确孤立的纯 RTL 执行时间。

### 真实录像定位

输入：`flight_20261004T184929_998838_6bb93c56`，2273 帧、960×720，原时间轴约 75.78 s。

- 每帧都通过实体 FPGA 和网口提取特征，共 2273 次硬件请求。
- 前 110 帧为 NOT_INITIALIZED；索引 110 起直到结束的 2163 帧全部为 OK。
- 保存 2163 个位姿、239 个关键帧；没有发生跟踪丢失。
- CPU ORB 调用数为 0；没有静默回退。
- 每帧特征数 261～936，平均 846.31。
- 特征请求平均 30.706 ms，最大 44.203 ms；电脑记录转换平均 0.123 ms。
- 整次回放耗时 177.13 s，包含词袋加载等启动开销，**尚未达到实时视频处理速度**。

300 帧有界试验也通过：前 110 帧初始化，后 190 帧正常跟踪。
相机内参仍为此前借用的临时参数；当前证据证明链路与建图，不证明定位精度、实际尺度或 ATE。

### 初始化适配及保留的失败

原版初始化只匹配第 0 层，而且要求至少 100 对匹配。当前 PL 的第 0 层最多 204 个点，
普通测试图仅 64 个。首次 300 帧网络接入完成了全部硬件请求，但未初始化，保留在 `slam_300`。

板上特征的有界诊断：相邻帧 0／1 仅第 0 层匹配为 36 对，全部层的同层匹配为 200 对；
150／151 为 95／544 对，240／241 为 109／624 对。

仅在 `--feature-mode fpga` 中，初始化改为使用各层同层匹配，原来的 100 对门槛、
双视图几何检查和后续建图检查保持不变。初始化和跟踪均采用当前 1000 点硬件配置。
`native/dump/inject` 模式继续使用原先的 `5*nFeatures` 初始化配置，CPU 基线行为保留。

## 源码与统一入口

- Linux 服务及 UIO 调度：`orb60/linux/server.c`、`engine.c`。
- 协议及电脑客户端：`orb60/linux/protocol.h`、`client.py`。
- 实体 golden 回归：`orb60/linux/test_board.py`。
- 初始化匹配诊断：`orb60/linux/diagnose_init.py`，不执行 CPU ORB。
- 运行时加载与设备树：`orb60/linux/load_board.sh`、`acz7015-orb60.dts`。
- SLAM 补丁：`rk3588/orbslam3_cpu_baseline/patches/0016-zynq-network-orb.patch`、
  `0017-fpga-multiscale-initialization.patch`、`FpgaORB.h`。

构建入口从统一环境读取工具路径，从已签核配对的生成寄存器头文件导出 ABI，
不手写猜测偏移。Linux ELF 使用 GCC 9.4 Cortex-A9 交叉编译，已在板上实际运行；
它不是 bare-metal BSP／ELF。固件转换使用 AMD Bootgen 2024.2。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File orb60/scripts/build_linux.ps1
```

该入口只构建，不自动部署；已实际重建并通过 C 调度、C 服务分包／CRC／错误处理、
ARM 构建和 Bootgen 转换。首次复现时 WSL 需要 `gcc-arm-linux-gnueabihf`、`device-tree-compiler`。

WSL 安装和回放入口，所有路径和网络端点均通过参数提供：

```bash
python3 "$WORKSPACE/orb60/scripts/install_slam_network.py" --source "$SLAM_ROOT" --workspace "$WORKSPACE"
cmake --build "$SLAM_ROOT/build" --target mono_euroc --parallel 2
python3 "$WORKSPACE/orb60/scripts/run_slam_network.py" \
  --slam-root "$SLAM_ROOT" --dataset "$DATASET" --camera "$CAMERA_YAML" \
  --host "$BOARD_ENDPOINT" --frames 300 --output "$NEW_OUTPUT_DIRECTORY"
```

`BOARD_ENDPOINT` 形式为 `IPv4:5600` 或 `[IPv6%interface]:5600`。
USB 网卡重新插入后 WSL 接口编号可能变化，按实际接口填写。
SSH 凭据及 UART 核对的主机密钥仅保存在忽略目录 `orb60/build/local`，不打包、不提交。

## 线协议 v1

64 字节 little-endian 头：`ORB60NET`、版本／头长、消息类型、frame_id、timestamp_ns、
width／height、role、budget 或 count、payload_bytes、status、CRC32、flags。
单连接单帧在途，支持 TCP 分段和连续请求；长度、容量、版本、身份、CRC 均检查。
仿真 replay 后端带独立标志，实体验证和 SLAM 适配器拒绝它。

成功结果为 128 字节元数据、`count*64` 原始 PL 记录、1024 字节逐层统计。
16 字节点与 64 字节摘要仍保留在板端；线协议返回完整特征和各层数量／偏移。
原始 PL 64 字节记录与 B1 的 float32 keypoint 布局不同，适配器执行明确转换，
按金字塔比例恢复图像坐标，并保留角度、顺序及 256-bit 描述子。

## 证据与下一步

本地证据根：`orb60/build/linux/bringup150`：

- `board_load.log`：实体运行时配置及 UIO 映射。
- `board_exact_9frames/result.json`：逐字节验证与实体耗时。
- `init_diagnostic/matches.json`：初始化匹配瓶颈。
- `slam_300/status.json`：原初始化未成功的试验，保留真实失败。
- `slam_multiscale_300/status.json`：有界建图试验。
- `slam_full_2273/status.json`、`TrackingStates.csv`、`FeatureTimeStats.csv`、
  `CameraTrajectory.txt`、`KeyFrameTrajectory.txt`：完整录像结果。
- `manifest.json`：签核 bit、寄存器头和 HLS 配对来源。

PS跨帧流水和鲁班猫路由器直连SLAM已进一步实现，实测、复现及边界见
[PS_FRAME_PIPELINE_20261021_ZH.md](PS_FRAME_PIPELINE_20261021_ZH.md)。保留同一150MHz bitstream。
下一步继续改善PS输入供给，并做更多场景及标定后精度评估。
实时相机采集、持续实时队列策略、端到端 60 FPS 和长时间热稳定性尚未验收。
5000 点配置仍未实现；它不是这次成功的前提，也未将输出容量改成 5000 冒充新增选点。
