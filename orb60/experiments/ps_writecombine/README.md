# ACZ7015 DDR 写合并试验：2026-10-21

本目录是独立的 PS/Linux 候选，未修改主线 Linux 服务、HLS、RTL、bitstream、SD 启动文件
或主会话的 SLAM 源码。采用 **自定义 Linux UIO 驱动**：标准 ARM 页表接口改善固定
DDR 窗口的 CPU 访问属性，无需新增 PL DMA。

## 实测结论

同一鲁班猫、eth0/路由器/千兆 PS_ETH、现有三帧窗口、相同 150 MHz bitstream 和
相同服务器二进制，180 帧交替普通图/942 点压力图/空图：

| 项目 | 原 UIO 映射 | 写合并 |
| --- | ---: | ---: |
| 特征提取和网口吞吐 | 44.59 FPS | **60.33 FPS** |
| PS 输入复制平均时间 | 11.224 ms | **1.349 ms** |
| 接收阶段平均时间（含 CRC/复制） | 19.198 ms | 12.954 ms |
| 结果快照平均时间 | 0.646 ms | 0.214 ms |
| 请求延迟 P99 | 73.919 ms | 55.774 ms |

吞吐提升 35.3%；两组完整原始特征记录均与独立 golden 逐字节一致。另有 9 帧 WC
测试覆盖两种 SLAM 角色。24 次空闲板卡复制短测，32 KiB 分块从 7.434 ms 降到
1.488 ms；每次检查整帧数据和前后保护区，最后恢复测试区原内容。

完整真实录像 2273 帧采用 WC 后处理 39.939 秒，**56.91 FPS**。此前相同源码、二进制、
内参及输入的保留结果为 49.902 秒、45.55 FPS；这是历史整段录像比较，不是本轮相邻的
完整视频 A/B。全部 2273 帧的特征记录 CRC 与保留版本一致，零 CPU ORB 调用，
索引 110 初始化，之后 2163 帧全部跟踪正常；输出 2163 个有限且时间递增的位姿。

60.33 FPS 是混合测试的平均特征链路吞吐；56.91 FPS 是本录像的平均 SLAM 处理速度。
它们不证明持续实时摄像头 60 FPS、单帧最坏耗时 <=16.67 ms 或定位精度已标定。

## 实现及兼容范围

- 固定器件 xc7z015，960x720、8 层、预算 1000，实际压力图 942 点；PL 不变。
- 两个 AXI-Lite 控制窗口仍为 Device/noncached。`0x20000000` 开始的整个 16 MiB
  专用 DDR 映射为 Normal noncacheable/write-combine，包含输入和结果缓冲。
- 现有服务一次 mmap 整段 DDR，因此临时替换整个 UIO provider，避免同一物理 DDR
  同时存在 Device/WC 两种用户态映射。寄存器地址、UIO map0/1/2、数据布局均保持。
- 驱动验证设备树的已有 reserved-memory/no-map 覆盖关系，并申请独占资源。
  不把 Linux 普通内存作为固定物理 DDR 使用，不创建内核 DDR 虚拟映射。
- 保留原服务的 DSB、PL 完成及写响应检查；WC 不等于可缓存，也没有省略可见性处理。
- 通过显式 driver_override 临时绑定。自定义驱动没有 generic-uio 的自动匹配表，
  不会在加载时自动夺取主线设备；同时限制单个 UIO 打开者。
- 配套内核是 **4.14.0-xilinx #52，2023-07-06 11:01:45**。出厂 `.config` 与板上
  `/proc/config.gz` 解压内容逐字节相同；使用出厂 Module.symvers，正常通过内核符号
  CRC 校验，未使用 force/ignore-vermagic。ARM 编译器 GCC 9.4，板上内核由 GCC 7.3 构建。
- 新驱动版本标识为 `wc1`，原始非缓存对照可用只读加载参数 `write_combine=0`。

固定保留 DDR 采用 `pgprot_writecombine` + `remap_pfn_range`，不改变普通 RAM 的缓存属性。
核心参考为配套 Linux 4.14 的 `drivers/uio/uio.c`、`include/linux/uio_driver.h` 和 ARM 页表实现。

## 当前板卡状态

测试后已恢复 `uio_pdrv_genirq`，driver_override 也恢复为原值 `uio_pdrv_genirq`；原服务器
重新监听 5600，WC 模块已卸载。原 ELF SHA256：
`b433953a6faa98dd2c36db24fc96e5c855e6ea0bbe6c5b56f5476c22d6aa60d8`。

WC 模块 SHA256：
`bdce5a843b2b63aa9fb4d8d01a3d10bdf0b4036c348543e3150c5cfe30af592f`。

Linux 因曾加载树外模块保留 taint=4096（O）诊断标记，卸载模块不会清除；没有强制加载
或内核错误。未为清除该标记重启板卡。

## 证据

本次构建目录：`orb60/build/linux/writecombine_20261021_side/`。

- `rk_summary.json`：同链路 A/B、完整视频、全部 2273 个记录 CRC 比较和源码哈希。
- `wc_full_acceptance.json`：未经修改的现有完整视频验收脚本输出。
- `rk/network_nc/`、`rk/network_wc/`：180 帧每帧特征 SHA256、延迟和复制时间。
- `rk/slam_pipeline2273/`：原始日志、运行状态、特征 CSV 和轨迹。
- `board_rk_nc.log`、`board_rk_wc.log`：PS 分阶段时间和接收/处理/发送完成计数。
- `kernel_provenance.json`：源码包 SHA256、配置与符号版本表 SHA256、构建时间。
- `restore_rk.log`：恢复原驱动及原服务的成功检查。

WSL 直连也做了单独试验，结果在 `result.json`、`network_nc/`、`network_wc/`；
这条网络路径较慢（27.27 ->30.39 FPS），不能混作鲁班猫链路的数字。

失败预检保留：首次拒绝了原有显式 override；第二次 SSH PATH 缺少 /sbin。两次均未
加载新模块。后续仅修复实验控制脚本，保留正常 ABI 检查和全部数据门禁。

## 复现入口

从项目环境运行 `build.ps1` 构建测试程序。驱动需要指定用户提供的配套内核构建目录；
禁止借用同名但不同构建的头文件或符号表。

```powershell
. ./scripts/project_env.ps1
./orb60/experiments/ps_writecombine/build.ps1 -Output <新的构建输出目录>
```

在 WSL 中用 `prepare_kernel.py --archive <出厂源码包> --output <输出目录>` 解包内核。
输出目录须先有板端下载的 `live.config.gz`；此入口校验配置，内核解包到新的 WSL
缓存目录，写出 `kernel_path.txt`。然后调用 `build.sh <输出目录> <内核目录>` 构建模块。

`experiment.py --output <输出目录>` 可自动运行 WSL 链路的原映射/WC 对照，并在 finally
中恢复原驱动。板卡必须已加载当前 PL、无其他活动客户端；SSH 配置沿用忽略目录的
受信 `board_router_ssh.json`。`run_board.py` 只通过已有固定主机密钥 SSH helper 操作。

原链路复现使用现有 `rk exec` 工作流和未修改的 `benchmark_pipeline.py`：

```text
python3 runtime/orb60_pipeline_20261021/sources/orb60/linux/benchmark_pipeline.py
 --host fe80::20a:35ff:fe00:122%eth0
 --images runtime/orb60_router_20261021/sources/test_images
 --descriptors runtime/orb60_router_20261021/sources/test_descriptors
 --frames 180 --window 3 --output <新的RK结果目录>
```

由 `activate_board.sh` 临时启用候选；所有客户端结束后必须调用 `restore_board.sh`。
原绑定值和设备路径保存在板端独立 `/tmp/orb60-wc-experiment-state`，恢复脚本可重复运行。
完整视频验证继续使用现有 `run_slam_network.py` 的 `fpga-pipeline` 模式，未改主线程序。

## 下一处瓶颈

WC 完整视频中输入复制约 2.30 ms、CRC 约 6.84 ms、接收阶段约 15.38 ms、PL 约
6.75 ms。接收时间包含 CRC/复制，不可再次相加；这些是并发运行下的墙钟时间。
后续优先比较 ARMv7 CRC 实现和 CPU/网络中断/PL 轮询的竞争。当前结果尚不是完整
SLAM 60 FPS 的签核，不需要先继续提高 PL 主频。
