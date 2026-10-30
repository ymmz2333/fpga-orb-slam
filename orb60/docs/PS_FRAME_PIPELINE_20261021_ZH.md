# PS 跨帧流水及鲁班猫 SLAM 实测（2026-10-21）

本轮采用 **PS 软件 pthread 流水 + 鲁班猫 std::thread 异步输入**。
既有图像、方向及描述子 HLS、AMD AXI/时钟逻辑和已加载的 **4PPC/150 MHz bitstream** 均未改变。
分辨率960×720、8层、容量1000、每层预算及原始64字节特征语义不变。

## 实现与所有权

- PS 接收线程处理 n+1 帧，唯一的 PL 调度线程处理 n 帧，发送线程回传 n−1 帧。
  `linux/pipeline.c` 使用两个容量3的索引队列，以及各3个接收槽和结果槽。
  槽位在互斥锁/条件变量下转交；队列满则阻塞并传播 TCP 背压，不丢帧、不覆盖。
- 三个输入槽位于保留 DDR 的偏移 `0x800000/0x900000/0xA00000`，每槽跨度1 MiB。
  均与原三 raw、两 blur、points/stats/features 工作区隔离。
  接收线程在32 KiB缓存块上递增 CRC，再写入所属输入槽；完整验证和屏障后才提交 PL。
  PL 第0层和描述子第0层直接读该槽，不再进行第二次整帧 DDR 复制。
  输入槽保持到整帧 PL 完成；结果先快照到独立缓存槽，发送完成后才能复用。
- MMIO 仍由唯一工作线程执行，原八层内部调度和写响应/可见性检查保持。
  不改变 UIO 非缓存映射，不引入缓存别名、DMA或新增硬件接口。
- 请求保留64字节 v1协议。每连接校验递增帧号/时间戳，FIFO保序；响应复核帧号、
  时间戳、角色、长度和CRC。坏帧不会启动PL；PL失败后服务停止，要求复位/重载。
- `fpga-pipeline` 模式使用独立图像生产、TCP发送、TCP接收线程，最多3帧未消费。
  SLAM读取结果后，后台继续预取后续帧，与当前 `TrackMonocular` 重叠。
  连接在词典/System初始化之后建立，避免启动阶段超时；结束时检查全部请求排空。
  初始化/普通提取配置均为1000，因此预取请求使用固定传输角色0；SLAM统计仍记录真实角色。
  `fpga` 同步模式、native/dump/inject和原初始化几何门槛保留。

## 实测结果

RK3588 eth0和FPGA PS_ETH均以千兆网线接同一路由器；电脑只经SSH调度。
使用记录视频，不包含实时相机采集；`--unpaced` 去掉回放限速。

| 测试 | 吞吐 FPS | 请求→结果 P99 / 最大 |
|---|---:|---:|
| 原 PS 同步服务，180帧混合图，窗口1 | 31.49 | 30.99 / 32.60 ms |
| 新 PS 流水服务，窗口1 | 33.05 | 28.20 / 31.56 ms |
| 新 PS 流水服务，窗口3 | **49.12** | 62.27 / 65.56 ms |
| 鲁班猫 SLAM，同步请求，同一300帧 | 14.60 | 29.65 / 30.40 ms |
| 鲁班猫 SLAM，异步流水，同一300帧 | **40.00** | 63.85 / 66.84 ms |
| 鲁班猫 SLAM，异步流水，完整2273帧 | **45.55** | 68.56 / 78.86 ms |

180帧交替输入普通280点、压力942点、空图；全部原始记录与独立golden逐字节一致。
此表吞吐包含主机验证开销；前三项测试时另有单工作线程RK编译任务，后续SLAM测试时编译已完成。
300帧对照使用相同可执行程序和源码，每帧特征数量及原始记录CRC一致，零CPU ORB调用。
两种模式均在索引110初始化，随后190帧跟踪正常。

完整2273帧处理49.902秒，全部按序发送/接收/消费，未丢帧；初始化后的2163帧均正常跟踪，
输出2163个有限、按时间递增的位姿。全部输入时间戳/特征数量与既有PC完整回放一致；
前300帧记录CRC与配对测试一致。轨迹受并行SLAM调度影响，不承诺轨迹逐字节相同；内参仍为借用配置。

完整视频提交特征请求→SLAM取用的P99/最大为 **87.08/132.03 ms**，
SLAM等待特征结果的平均/P99为 **9.22/25.87 ms**。前者包含预取排队，终点为特征取用，
不等同于最终位姿发布延迟，也不包括相机采集。三帧窗口提高吞吐，同时增加单帧排队延迟。
本轮没有达到端到端60 FPS，不能用PL核的5~6 ms代替系统帧率。

板端完整视频计数：received=processed=sent=2273；输入ready水位1、结果ready水位2，
主机最大未消费/结果队列均3。接收与PL重叠15.710秒，PL与回传重叠54.68 ms，
三阶段同时活动45.74 ms；这些是活动区间交集，不是独立CPU计算时间。

## 当前瓶颈和未保留候选

原同步Profile平均：接收8.89 ms、输入CRC4.18 ms、DDR复制7.53 ms、PL5.32 ms。
流水混合输入中接收阶段平均20.14 ms（已含CRC6.01、DDR写入11.25 ms），PL约5.66 ms。
DDR理论带宽不是当前主因；PS非缓存写入、CRC及CPU调度限制输入供给。
接收时间包含等待，不能与CRC/复制再次相加。

有界试验把输入DDR写入改为对齐64位整数STRD，功能golden通过，
但吞吐46.69 FPS、请求P99 75.01 ms，比49.12 FPS版本差，已撤出默认路径。
实验源码保留在 `experiments/ps_copy64/`，二进制和失败性能候选结果保留，不能标为优化成功。
下一步若继续优化搬运，应单独验证内核驱动的合法写合并/缓存维护路径；不能直接把UIO映射改成缓存而省略一致性处理。

## 复现与回滚

源码入口：`linux/server.c`、`pipeline.c`、`engine.c`、`stream_crc.h`；
SLAM补丁为 `0018-fpga-frame-pipeline.patch`，以及 `FpgaPipeline.h/FpgaReplayInput.h/FpgaORB.h`。
原0016/0017补丁仍需依次安装；`scripts/install_slam_network.py`可重复执行。

```bash
# 复用已签核寄存器头；构建主机门禁、静态ARM服务。
bash orb60/linux/build.sh OUTPUT_WITH_ORB60_REGISTERS_H
# 板端已完成运行时overlay/UIO配置时，只启动PS服务，无需重新加载bit。
orb60-server-arm --uio /dev/uio0 --pipeline --profile
# 鲁班猫已有依赖及词典；SDK/CPU原始版本另存备份。
python3 orb60/scripts/install_slam_network.py --source SLAM_ROOT --workspace WORKSPACE
cmake --build SLAM_ROOT/build --target mono_euroc -j1
python3 orb60/scripts/run_slam_network.py --slam-root SLAM_ROOT --dataset DATASET \
  --camera CAMERA_YAML --host '[fe80::20a:35ff:fe00:122%eth0]:5600' \
  --platform rk3588 --interface eth0 --feature-mode fpga-pipeline --unpaced --frames 0 --output NEW_OUTPUT
```

板端当前运行 `/tmp/orb60-server-pipeline --uio /dev/uio0 --profile --pipeline`，
日志 `/tmp/orb60-pipeline-final.log`；可用已保留的原服务和 `switch_server.sh` 回滚。
未改SD启动文件，未重新编程PL。鲁班猫同步版源码/二进制备份在
`runtime/orb60_pipeline_20261021/sync_snapshot/`，当前程序可直接选 `--feature-mode fpga` 回到同步请求。

本地证据位于 `build/linux/frame_pipeline_20261021/`：
`ps_gates_final.log`、`cpp_gate.log`、`slam_replay_gate.log`、`baseline_window1.json`、
`pipeline_window1/`、`pipeline_window3/`、`slam_pair300.json`、`slam_pipeline2273/`、
`board_final.log`及`full_acceptance.json`。合成模型测试与实体板结果分开标识。

交付增量包 `orb60_ps_frame_pipeline_150mhz_20261021.zip` 包含原150MHz bitstream、
PS ARM服务及源码、SLAM补丁、golden输入/特征、复现脚本和实测证据。
完整FPGA HLS源码继续沿用此前发布工程，本轮没有生成新bitstream。
包内不含SSH密码、私钥、本机配置、词典或原始整段视频。
