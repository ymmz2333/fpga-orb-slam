# ACZ7015 DDR 配置驱动的仿真容量模型

2026-10-13。修改对象仅为原生 Verilator 的 C++ DDR harness 和对应验证入口；
不改变 HLS/RTL、算法、PS 固件、时序约束或既有发布产物。
实现选择为计算机软件模型，实际 DDR/AXI 基础设施继续使用 AMD IP。

## 配置与口径

新入口从冻结的 `vivado/ps_config.tcl` 读取位宽和 DDR 时钟，而不是写死
“全板只有 800/1600 MB/s”。当前参数为 32 bit、533.333333 MHz，DDR 双沿，
物理总线峰值为 4,266,666,664 bytes/s，约 4.267 GB/s。板卡 1 GB 是容量。

- DDR 的读、写共同消耗一个总预算。每个模拟 AXI 数据拍按 8 字节消耗预算，
  包括未使用字节槽和窄写；有效写字节另按 WSTRB 统计。
- 每个 64 bit HP 的读、写方向独立限速；每方向每个 HP 时钟最多一拍。
  100 MHz 每方向 800 MB/s，125 MHz 每方向 1000 MB/s。
- 同一 HP 的多个读主机共享其读预算，多个写主机共享其写预算；同时读写可并行。
- HP0/1 对应 DDRI 端口 3，HP2/3 对应端口 2。记录这个拓扑，但不凭空增加
  未经核对的内部时钟/端口带宽限制；内部 DDRI 排队与仲裁并非逐周期 AMD-IP 模型。
- 使用整数分数累加控制 bytes/s，不把 4.267 GB/s 向上取整成固定整拍配额。
  空闲周期只保留不足一拍的分数，不积累整拍信用形成不真实的后续突发。
- 保留读资格延迟 0–50/400–600 ns、写响应 20–310 ns 和 0/27% 随机停顿对照。
  这些是敏感性实验条件，不是该板的实测延迟或效率。

**这是按实际工程参数计算的容量上限模型，不是实测有效 DDR 带宽。**
尚未模拟 DDR bank/row、刷新、读写换向、PS/CPU 争用和 AMD DDR PHY。
不能把这个新模式的 FPS 直接称为板上 FPS，也不能把更宽松模型相对旧模型的
时间下降当作算法或硬件优化收益。

来源：

- [小梅哥 ACZ7015 官方 DDR 型号与位宽](https://fpga.cn/forum.php?mod=viewthread&tid=29414)
- [AMD Zynq-7000 DDR/HP 互连](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Interconnect)

## 入口与历史兼容

新入口默认使用上述板卡配置。参数路径通过项目统一环境发现；无新增本机路径。

```powershell
# FrameJob 是已经完成、通过精确验证的原生整帧 job。
./orb60/scripts/board_ddr_frame.ps1 -FrameJob <accepted-native-frame-job>

# 若随后实测有效聚合带宽约 1 GB/s，可改总预算；HP 仍按当前时钟分别限速。
./orb60/scripts/board_ddr_frame.ps1 -FrameJob <accepted-native-frame-job> -EffectiveDdrMBps 1000
```

该入口读取已验收的、冻结的图像与描述子 RTL；重新生成 wrapper 和寄存器头，
核对其与原编译模型逐文件一致后，在新 scratch 目录复制原 Verilator 缓存。
只重编译新的 C++ harness。原 job、原缓存、原输入和原结果不修改。
若缓存或配对核对失败，保留失败证据；不得绕过核对或沿用旧 exe。

每次先运行 pin-stub DDR 模型检查，再重放一个历史高延迟/受限带宽用例，要求
三帧 cycles、流量、选点、逐层结果、AXI 与 FIFO 统计精确一致。
然后运行新容量模型四组 DDR 条件 × 普通 280 点/压力 942 点/空点三帧。
全部继续核对原独立 golden 的图像、排序、完整描述子记录及 DDR guard，
并核对最终写响应、4 KB 边界、所有权、实际未完成请求和读写预算守恒。

既有 `native_frame.ps1` 的 800/1600 MB/s 压力门禁和旧命令行保持原行为，
用于历史精确比较。新的板卡容量评估使用 `board_ddr_frame.ps1`；不替换或改写
先前发布的 performance.json、时序报告和 bitstream。

输出包含 `board_ddr_config.json`、配对 SHA、编译/仿真日志和 `performance.json`。
其中 `effective_bandwidth_measured`、`physical_board_fps_verified` 均为 false，
后续有真实板上测量时再显式设置有效预算并记录测量条件。

## 本轮验证结果

100 MHz job：`build/optimized/gates/20261013_123043_board_ddr_efcdae87`。
125 MHz job：`build/optimized/gates/20261013_122542_board_ddr_ced10303`。
两者终态均为 SUCCEEDED/COMPLETE，pin-stub 模型检查和编译/复位启动通过。
每个频率的新模型 12 帧全部精确，另各 3 帧历史模式回归的周期、流量、
每层计数/耗时、AXI 和 FIFO 统计完全相同。共验证 24 帧新模型、6 帧兼容回归。
板卡配置解析、1000 MB/s 覆盖、负值/超物理峰值/低于一字节每秒的非法预算拒绝、
脚本语法检查通过。

| 条件 | 4PPC/100 MHz 普通/压力 | 4PPC/125 MHz 普通/压力 |
|---|---:|---:|
| 板卡容量、0% 停顿、0–50 ns 首读资格延迟 | 8.30082 / 8.98230 ms | 6.67181 / 7.25846 ms |
| 板卡容量、0% 停顿、400–600 ns 首读资格延迟 | 8.30684 / 8.98853 ms | 6.67794 / 7.26708 ms |
| 板卡容量、27% 停顿、0–50 ns 首读资格延迟 | 8.52487 / 9.19881 ms | 6.92458 / 7.50334 ms |
| 板卡容量、27% 停顿、400–600 ns 首读资格延迟 | 8.53778 / 9.20849 ms | 6.92238 / 7.52062 ms |

普通图仍为 280 点，压力图仍为 942 点；每个条件同时检查空图。
无随机停顿/低首读延迟的普通图模型帧率约 120.47 / 149.88 FPS，
压力图约 111.33 / 137.77 FPS。四个条件中的最大压力耗时分别为
9.20849 / 7.52062 ms。这里没有新的 FPGA 优化收益或实际板上 FPS 结论；
相对历史模型的差异来自 DDR 模型容量和 HP 读写通道限速口径改变。

现有 HLS、RTL、PS、时序/资源报告及 bitstream 不变，不重新综合或路由。
