# Slice 优化：先判断方向，再完整验收

依据用户 2026-10-13 最新指示“少做基线测试，多多试一下优化方向是否正确”，
本轮采用三个有界对照。保留已有精确基线结果，不重跑基线，不将试验写成新发布验收。

## 两 bank 完整路由

`20261012_231455_tournament_banks2_7dbd9503` 完成 HLS 门禁：21 个精确 co-sim
事务通过，八个 score bank II=1，实际 tree 两 bank，BuildTournament II=2、深度 2
（三 bank 深度 13）。HLS 估计较三 bank 减少 2784 LUT、2302 FF、5 BRAM18、6 DSP。
最大 co-sim 周期仍为 356045；平均 106050 -> 105948。

使用此冻结 HLS/IP 和未改变的第一阶段描述子做 100 MHz 完整路由，保持原
布局策略和全部时序/DRC/覆盖门禁。这个试验回答代码改动是否降低真实 Slice 并满足
时序；随机 AXI、整帧和发布验收后补，不能继承三 bank 的整帧结果。
入口：`scripts/two_bank_route_experiment.ps1`。

2026-10-13 已检查任务 `20261013_000643_two_bank_route_probe_683203c2` 及其完整
route 子任务 `20261013_000643_orb_100mhz_1cac1aa7`，均 SUCCEEDED。
最新结果来自完整 routed top，未生成新的发布 bitstream：

| 指标 | 第一阶段自动三 bank | 显式两 bank | 变化 |
|---|---:|---:|---:|
| LUT | 30529 | 28902 (62.56%) | -1627 |
| FF | 29693 | 28748 (31.11%) | -945 |
| BRAM tile | 67 | 64.5 (67.89%) | -2.5 |
| DSP | 55 | 39 (24.38%) | -16 |
| Slice | 10534 (91.20%) | 10239 (88.65%) | -295 |
| 控制集 | 1075 | 1058 | -17 |
| WNS / WHS | +0.270 / +0.040 ns | +0.316 / +0.046 ns | 均通过 |

TNS/THS 为零，setup/hold 失败端点为零，完整约束/路由/严重 DRC 门禁及扩展
200 端点 / 50 网络诊断通过。最差路径仍为 FAST lane1 分数计算，13 级逻辑、
9.408 ns 数据路径。两 bank 消除了三 bank 地址映射的主要资源开销，但较原发布版
仍多用 606 Slice（原版 9633）；不能把 88.65% 占用解释成可直接复制两套像素核。
该候选随机 AXI 与整帧验证仍待完成，不能继承三 bank 的原生帧结果。

## 描述子位宽两项 HLS 试验

实现选择为自定义 HLS。构建参数 `DescriptorWidthMode` 仅影响内部类型，没有
新增 MMIO 字段；默认模式 0 保留原 32-bit moments、64-bit CORDIC 行为。
数据源、合法性检查、外部坐标/score、64 字节记录、算法、排序和错误排空均保留。

| 模式 | 改动 | 比较 |
|---|---|---|
| 1 | moment 累加器及跨点字段改为 signed 21-bit | 相对已验收模式 0 |
| 2 | 在模式 1 上将 CORDIC X/Y 改为 signed 43-bit、Z 改为 signed 34-bit | 相对模式 1 和模式 0 |

`prove_descriptor_widths.py` 从冻结 kUmax 和 CORDIC 常数独立计算范围：m10/m01
各为 ±624240；按每次移位的 ceil(abs/2^k) 保守界证明全部 32 次迭代，X/Y 最大
绝对界 3121259220830，小于 2^42；原角度累加、象限处理及 full-turn 归一化可用
signed 34-bit。不会直接把方向矩 21-bit 套到带 20 位小数的 CORDIC 内部。

两模式用完全相同冻结源码，仅改变编译定义。每项运行已有独立 golden 的 38 个
精确 CSim 事务和 C 综合，跳过 co-sim/IP 导出/大整帧回归。比较实际必需循环 II=1、
四路 64-bit/32-bit AXI、生成 moments / angles FIFO 宽度（202 / 234 bit），及
各项 HLS 资源和估计周期。CORDIC 算法、常数、向下取整及 A32 量化保持精确。
入口：`scripts/descriptor_width_probes.ps1`。

任务 `20261013_000643_descriptor_width_probes_946aeedd` 已 SUCCEEDED；两种
模式各 38 项精确 CSim 通过，必需循环均真实 II=1，四路 AXI64 / 地址32，
moments/angles FIFO 实际宽度 202/234 bit。以下为 HLS 估计：

| 模式 | LUT | FF | DSP | BRAM18 | 相对模式0 |
|---|---:|---:|---:|---:|---|
| 0 原类型 | 17844 | 13677 | 7 | 35 | 保留历史结果 |
| 1 moment21 | 17693 | 13621 | 9 | 35 | -151 LUT / -56 FF / +2 DSP |
| 2 再加 CORDIC43/34 | 16673 | 13550 | 9 | 35 | -1171 LUT / -127 FF / +2 DSP |

主要节省来自 CORDIC 缩窄，相对模式1再减少 1020 LUT。三者估计周期均为
12.077 ns，不代表实际 WNS。选模式2重建其原冻结源码的 co-sim/IP，随后与两 bank
图像核做完整100MHz route；`SourceProbe` 明确表示重新验证方向试验快照，不继承
未完成的 RTL 门禁。复现入口：`scripts/descriptor_width_route_experiment.ps1`。

选择明显有效的候选后再跑 co-sim、随机 AXI、共享 DDR 整帧和完整路由；HLS 估计
不能作为真实 Slice/WNS，C 仿真不能作为 RTL 门禁。描述子跨行预取仍为性能优先项，
该有界 Slice 对照不扩展为长期前置工程。PS 和上板仍暂缓。
