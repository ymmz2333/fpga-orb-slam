# R11 ORB：150MHz吞吐优化交付

固定960×720、8层、xc7z015clg485-2；4PPC图像核与精确方向/BRIEF核。
性能选择按用户指定的4GB/s充足带宽、无合成随机停顿、0–50ns首读。
像素、点数与排序、方向/A32、描述子和64字节记录保持逐字节一致。

## 实测电脑门禁

| 输入 | 整帧RTL耗时/ms | 等效FPS |
|---|---:|---:|
| 普通280点 | 4.87438 | 205.15 |
| 压力942点 | 5.14584 | 194.33 |
| 空点 | 4.80405 | 208.16 |

这是两核真实RTL共享DDR模型的结果，不是板上视频帧率。
4GB/s是用户提供的可用带宽预算，HP/仲裁限制仍存在于模型中。
其他DDR停顿配置保持功能回归与诊断；不用于选择性能候选。

## 完整路由

WNS **+0.093ns**，WHS **+0.036ns**；TNS/THS为零。
Setup/hold、时钟与约束覆盖、完整路由及严格DRC均通过。

| 资源 | 已用/总量 | 利用率 |
|---|---:|---:|
| LUT | 34990/46200 | 75.74% |
| FF | 37001/92400 | 40.04% |
| BRAM tile | 70.5/95 | 74.21% |
| DSP | 44/160 | 27.50% |
| Slice | 11452/11550 | 99.15% |

## 保留的优化

- FAST/NMS窗口每行并行初始化，去除旧串行清零循环。
- 方向矩按原row/word顺序连续接收，窄化计数器；避免31个行循环的串行等待。
- 锦标赛BRAM增加读取寄存器；node255..2保持II=2，根节点在循环排空后更新。
  真实RAW distance2经逐bank/address枚举证明，不隐藏依赖或增加时序例外。

新前端21个C/RTL事务通过；相同SHA后端的38个C/RTL及6个随机协议事务
按配对记录复用。新前端随机AXI/复位/完成屏障、12个原生整帧、
12个4GB/s整帧和3帧旧模型重放精确通过。完整top重新路由。

## 源码、产物与复现

- [源码](../experiments/frequency_speed_joint/FPGA_ORB_HLS/fastv2/next/src/)
- [逐核冻结输入](../frozen/speed_joint_150mhz/)
- [150MHz bit](../artifacts/speed_joint_150mhz/orb60_150mhz.bit)
- [完整时序](../evidence/speed_joint_150mhz/route/post_route_timing.rpt)
- [完整资源](../evidence/speed_joint_150mhz/route/post_route_utilization.rpt)
- [4GB/s精确整帧](../evidence/speed_joint_150mhz/board_4gb/performance.json)
- [相同150MHz/DDR对照](../evidence/speed_joint_150mhz/board_4gb_comparison/SUMMARY_ZH.md)

```powershell
pwsh -NoProfile -File tools/verify_integrated4.ps1
pwsh -NoProfile -File orb60/scripts/verify_speed150.ps1
pwsh -NoProfile -File orb60/scripts/reproduce_speed150.ps1 -Mode Inputs
pwsh -NoProfile -File orb60/scripts/reproduce_speed150.ps1 -Mode All
```

All入口重新生成本版150MHz HLS/RTL、协议、整帧、完整route与bit；耗时较长。
Inputs入口已在本分发目录成功执行，独立生成38组方向/描述子golden。
各硬件门禁已分别通过；没有额外重复执行All串联重建。
不需要重新测试125MHz，仅读取其已发布寄存器定义验证接口一致。
新bit的MMCM要求PS FCLK输入100MHz，内部核为150MHz。
PS/BSP/ELF/XSA及板上验证仍暂停，原三核ELF不能视作这版bit的配套软件。
本交付未进行任何JTAG/非易失编程。

Bit SHA256：`b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60`。
