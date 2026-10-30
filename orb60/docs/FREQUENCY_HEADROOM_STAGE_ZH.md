# R11 主频探索：模式2、方向矩融合与精确量化

用户最新目标为自主持续提高可完整路由的主频，不再按启动/通知进程号/
等待用户确认的旧流程停下。沿用Z015、960×720、8层及精确输出，PS与板测暂缓。

## 设计选择与修改依据

选择自定义HLS处理精确算法；AXI-Lite切片、时钟/复位继续使用成熟AMD IP。
尚未发现必须改成手RTL的新热点，不修改生成RTL，也不增加时序例外。

- 采用已通过的36bit锦标赛排序键（模式2）。BRAM点表模式3虽少用LUT，
  完整Slice反而99.26%，因此不保留。原41bit点内容由格号读出，排序/输出不变。
- 采用已通过的方向矩接收融合模式1，释放raw patch存储与串行扫描。
- 原A32六次搜索的真实路径为13级逻辑，更新lo/hi反馈。新实现用严格整数
  范围判断、固定移位和常数乘法消除反馈。`1457×45=65536+29`，有效商输入
  q≤1439时不会越过下个整数门槛；完整uint32加法溢出和原搜索超范围钳位也保留。
  独立整数golden遍历全部23,592,960个有效Q16角度；另100万完整32bit输入
  对拍旧搜索及20项边界/溢出，通过。150MHz HLS量化器II=1、延迟2拍、1DSP。
- 测得GP0 WSTRB直接驱动184个寄存器更新端，7.504ns中6.291ns来自布线。
  在每个核的AXI-Lite控制端放AMD Register Slice，首版Light模式7；DDR端不变。
- PS FCLK0固定100MHz，AMD Clocking Wizard输出目标高频，PL与HP/GP同域。
  150MHz配置验证通过，MMCM乘数19.875/输入除数2/输出除数6.625，输出精确150。
  HLS/C/RTL、协议与整帧模型均使用重新生成的相应频率RTL。

之前2770负载的“ap_enable寄存器”路径经完整报告确认从proc_sys_reset出发，
属于复位分发；不能只看终点名称把它误记成图像计算使能。后续依据新完整
路由再决定是否需要局部复位结构。5505负载FAST CE也持续记录，不能忽略背压。

## 入口与验收顺序

作者快照：`experiments/frequency_headroom/`。旧发布源码/报告/bit保持。

```powershell
./orb60/scripts/frequency_pair.ps1 -Period (1000.0/150) -DescriptorVectors <frozen-vectors>
./orb60/scripts/orb_frequency_timing.ps1 -FrequencyMHz 150 -AcceptedLayer <carrier> -AcceptedDescriptor <carrier> -ExtendedDiagnostics
```

`hls.ps1`新增AuthorRoot、SliceCompactMode和DescriptorFastQuantize，默认值
保持原入口行为，冻结快照和replay严格校验其取值，不将新源码写入旧job。
`compare_frequency_pair.py`检查36bit/8bank、II、量化反馈实际消失、raw融合、
四AXI64/address32及数字寄存器定义相同，已有II/C/RTL门禁继续独立执行。
随后新RTL运行随机AXI、共享DDR整帧及完整routed top；失败证据保留。

首目标150MHz；依据真实关键路径再选择约143/167MHz邻档，不凭旧WNS缩放。
完整top保持原Vivado策略且不追加post-route phys-opt；硬门槛setup/hold通过、
TNS/THS0、约束完整、路由无错误/严重DRC，争取WNS≥+.2ns。

## 时间与DDR模型

原800/1600MB/s、HP800MB/s压力口径保留；新板卡容量模型不改成算法收益。
每档以固定字节/s、固定ns首读延迟比较，新PL时钟只决定边沿量化。
6.666…ns在原生时间以6667ps表示，并显式记录该量化；真实route使用MMCM
150MHz生成时钟。奇数ps周期的半周期拆成floor/ceil，避免每拍少1ps。
Pin模型已验证10000/8000/7000/6667/6000/5000ps、容量守恒、读写/背压/
最终响应与复位。最初6000ps检查暴露测试等待40拍小于最大310ns B响应，
修正为原400ns观察窗再全档通过；不修改模型延迟或降低协议完成门槛。

新AMD控制切片/时钟结构的BD配置验证不等于完整RTL协议或路由验收。
原生核仿真不包含PS7/MMCM/AMD控制切片行为，板上带宽、缓存、视频、功耗
继续是独立板测门槛。新bit若最终交付，PS必须提供100MHz MMCM输入，不能
沿用旧125MHz FCLK初始化；暂未构建新ELF/BSP。

## 当前状态

150MHz两核C/RTL、实际II/接口/MMIO、随机AXI/复位/最终响应、12帧共享DDR
整帧及完整routed top全部通过。联合证据：
`build/optimized/comparison/20261013_145444_frequency_pair_db4fcbb9/joint_result.json`。

| 指标 |150MHz完整top|
|---|---:|
| WNS / WHS |0.000 / +0.041 ns|
| TNS / THS / 失败端点 |0 / 0 / 0|
| LUT / FF |34894 / 36886|
| Slice |11420 / 11550 (98.87%)|
| BRAM tile |70.5 / 95 (74.21%)|
| DSP |44 / 160|
| 控制集 |1133|

WNS仅达到硬门槛，未达到+.2ns余量目标，因此保留为已验证探索版本，
不能宣称主频提升已经稳定收敛。未生成新bit或PS固件，也未上板。
相对发布125MHz：LUT-657、FF+764、BRAM-3.5、Slice-17；主频+20%，
不能把这一组混合修改的变化都归因于一个独立优化。

同800/1600MB/s及首读ns条件，相对已融合125MHz整帧：普通图宽松条件
7.02309→6.35414ms，压力图7.66342→7.15458ms；受限压力最大
11.99879→11.68069ms。新1GB/s聚合容量模型四组条件中，普通图最大
8.30692ms、压力图最大9.81044ms（独立board_ddr job dff2015e原始记录）。
这些是模拟结果，不是物理板或视频P99测量。频率仿真记录为6667ps，
完整route时钟为MMCM150MHz，不掩盖两者的量化区别。

## 新热点与下一步

150MHz最差变成bank2的token[45]到score寄存器CE，7级、6.105ns；
原先动态读取26格分数的选择器仍处于比较/更新反馈链。
新`experiments/frequency_local_scores/`让26格各自比较本格寄存器，
只有payload写使能归约“是否更新”，不再从动态选中分数驱动所有score CE。
保留真实同格反馈和严格大于（同分保持先到），无dependency例外。
已有67项sorted-grid/golden通过，新6ns层核C/RTL正在运行。
复用相同6ns后端前逐文件核对descriptor源、全部include、独立reference
及向量元数据；不会把8ns/6.667ns旧RTL用于6ns频率比较。

另保留原bank结构的6ns控制对照：两核C/RTL与II/结构/MMIO已通过，
随机AXI运行中。后续比较两个166.667MHz完整top的真实路径和资源，再决定
继续局部流水或选择邻档频率；不凭150MHz WNS推算更高档通过。
