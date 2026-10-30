# 4PPC 前置优化：第一阶段开发状态

主线仍是 4PPC / 100 MHz 与描述子协同加速，2PPC / 125 MHz 为后续对照。
本阶段实现选择为自定义 HLS；已有 AMD PS7 / AXI / 时钟 / 复位基础设施保留。
仅已测得的局部更新热点在 HLS 不达标时考虑 RTL，当前没有修改生成 RTL 或 PS。

## 已实现，HLS 门禁通过，后续门禁待完成

- 候选按 `cell & 7` 分流到八个独立、26 格的更新 actor。分数寄存器保留真实依赖，
  小型 payload 使用 LUTRAM，末尾按原 cell 顺序收集并排空四个填充格。
- 超预算选点采用 256 叶锦标赛树；比较规则保留分数、y/x、最后的 cell 优先级。
  叶节点清空后只重建八级祖先。双口存储建树要求 II<=2；候选更新仍要求八个 actor 都 II=1。
- FAST 的配对 X / 单独 Y 几何表由生成器压成连续分段、带 lookahead sentinel。
  当前 X 322 项、Y 155 项，均包含每层 sentinel；旧单像素和 Resize 表仍供各自算子使用。
- 描述子拆成方向矩、精确 CORDIC/A32、BRIEF 三个 DATAFLOW actor，跨点重叠。
  raw / blur 双缓冲由各自消费者独立持锁；错误后继续排空，保存同样的有效输出前缀。
- 原生 RTL harness 增加生成器绑定的 actor busy、真实 FIFO push/pop、背压和水位观测。
  actor busy 包含等待，不能直接当作纯计算时间；每个 FIFO 的占用必须合法，整帧结束为空。
  不增加 MMIO 寄存器，也不编辑任何生成 RTL。

## 当前验证边界

27/27 主机测试通过，包括原有测试、八层前端、连续同格/同分、精确排序、942 点、
变化输入/全部方向、边界和部分错误。新几何表示另与未改动的 baseline 表逐项核对。
独立 Python 向量的 38 个 descriptor 事务在新原生 C++ 实现上逐字节通过。
仿真 profile 绑定已使用旧版实际生成 RTL 做 wrapper / DDR pin-stub 检查；这些不构成
新核 RTL 正确性或新性能证明。

2026-10-12 已完成冻结 job `20261012_202829_architecture_stage1_ceed5a35`：
layer2 的 21 个和 descriptor 的 38 个 C/RTL co-sim 事务精确通过；八个 score bank
真实 II=1，三个描述子 actor 和四个 64-bit AXI 端口检查通过。详细对照见
[ARCHITECTURE_STAGE1_HLS_RESULTS_ZH.md](ARCHITECTURE_STAGE1_HLS_RESULTS_ZH.md)。
这些结果不构成随机 AXI、共享 DDR 整帧或 routed WNS 验收。

`scripts/architecture_stage1.ps1` 先复核主机与独立向量，再分别冻结源码、运行 100 MHz
layer2 / descriptor CSim、综合、21 / 38 事务 co-sim；严格核对八个 II=1 reducer、
分流/收集流水、64-bit AXI、三个独立描述子 actor 和锦标赛建树 II。与两核旧基线
分别比较资源估计、周期。任何失败保留原始证据，不启动后续 route 或宣称通过。

## 后续顺序

完整后续计划已更新到 [NEXT_OPTIMIZATION_PLAN_ZH.md](NEXT_OPTIMIZATION_PLAN_ZH.md)。
新增高扇出/控制集/不同路径诊断、400~600 ns 首读延迟用例、FAST 明确拆级和
raw 加载时计算方向矩；保留 4PPC 主线及现有第一阶段实现，不改变正在运行的冻结门禁。

本阶段 HLS 通过后：新 RTL 随机 AXI -> 带 profile 的共享 DDR 整帧 -> 完整路由，
确认局部结构与描述子流水收益，再推进 4PPC、搬运双缓冲、2/4/8 未完成读请求、
BRIEF 1/2 比较每拍与 64/32-bit patch 存储对照。跨频率比较保持相同 DDR 字节/s
与响应 ns 延迟，使用实际重新生成的 RTL。

这轮 HLS、随机 AXI 及四种 DDR 配置下的 12 帧原生回归已通过。整帧对照见
[ARCHITECTURE_STAGE1_FRAME_RESULTS_ZH.md](ARCHITECTURE_STAGE1_FRAME_RESULTS_ZH.md)。
原配置下压力图改善仅 0.360% / 0.035%；高首读延迟时压力图为 28.91 / 30.84 ms。
真实取数延迟是新增明确瓶颈，下一候选提高跨行预取优先级；完整路由仍待验收。

原 100 MHz bitstream 和冻结编译输入保持原验收版本；上述修改尚没有新 routed
bitstream。第一阶段三 bank 快照的 route 与报告汇总恢复已通过，结果见
[ARCHITECTURE_STAGE1_ROUTE_RESULTS_ZH.md](ARCHITECTURE_STAGE1_ROUTE_RESULTS_ZH.md)。
当前开发源码已加入锦标赛显式两 bank 的独立实验，不能继承三 bank 的 routed 结论。
PS、实体板与 60 FPS P99/max 验收继续暂缓。
