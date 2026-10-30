# 第一阶段路由结果与资源选择

原 job `20261012_222118_orb_100mhz_ae11f62c` 完整路由和硬门禁通过，最终被 Python
诊断汇总标为 FAILED：BRAM 自反馈路径同一个时钟引脚在 launch / capture 两处出现，
原解析器将其误判为重复的数据路径边界。原失败状态、日志、报告和 routed DCP 保留。

恢复 job `20261012_225220_stage1_route_diagnostics_recovery` 仅修正汇总，按目的数据
引脚之前的唯一 launch 行截取。严格复核原 IP / 工具 / 源码哈希、时序表、覆盖、
路由、严重 DRC、200 个不同 setup 端点及 50 个物理网络后完成 SUCCEEDED。
没有重新综合或布线，没有弱化门禁，没有生成新 bitstream。

## 完整 routed top（xc7z015clg485-2，100 MHz）

| 指标 | 原保留版本 | 第一阶段三 bank 快照 | 变化 |
|---|---:|---:|---:|
| WNS / ns | +0.238 | +0.270 | +0.032 |
| WHS / ns | +0.035 | +0.040 | +0.005 |
| TNS / THS | 0 / 0 | 0 / 0 | 通过 |
| LUT | 27,033（58.5%） | 30,529（66.08%） | +3,496 |
| FF | 27,169（29.4%） | 29,693（32.14%） | +2,524 |
| BRAM tile | 68 / 95 | 67 / 95 | −1 |
| RAMB36 / RAMB18 | 59 / 18 | 52 / 30 | 物理配置变化 |
| DSP | 40 / 160 | 55 / 160 | +15 |
| Slice | 9,633（83.4%） | 10,534（91.20%） | +901 |
| 控制集 | 1,160 | 1,075 | −85 |

56,445 个可路由网全部完成，路由错误为零；setup / hold 失败端点均为零，
no_clock / unconstrained_internal_endpoints 为零，无 Error / Critical Warning DRC。
388 项普通 DRC Warning 保留在报告中，包含 DSP 输入 / 输出流水提示等。

最差路径仍是 FAST 13 级比较链，数据路径 9.554 ns（逻辑 3.878 / 布线 5.676 ns），
数据扇出 25。前 200 路径中的非 FAST 热点为锦标赛 BRAM 写入，代表 WNS +0.588 ns、
8 级；原全局候选 CE 更新反馈已不在这 200 条最差路径中。

## 实际资源热点与下一对照

`consume_and_select` 从 3,229 LUT / 4,155 FF / 0 DSP 增为
6,053 LUT / 5,394 FF / 16 DSP；其 RAMB36 / RAMB18 为 8 / 7。
图像核整体为 19,556 LUT / 15,264 FF / 49.5 BRAM tile / 45 DSP，
描述子为 8,545 LUT / 11,585 FF / 17.5 BRAM tile / 10 DSP。
分段表节省的 BRAM 被新选点结构部分抵消，不能沿用 HLS 估计宣称大幅释放资源。

在生成 RTL 中，锦标赛数组被 HLS 自动分为三个 bank，地址映射出现 683 / 342 等
常数乘法。当前新增的有界候选仍用 **自定义 HLS**：对 `tree[512]` 明确奇偶两 bank、
真双口 BRAM，两个子节点位于不同 bank，父写入与其中一路读取使用两个端口。
保留真实 RAW 依赖与建树 II<=2，不增加 DEPENDENCE false，不修改生成 RTL。

由 `scripts/tournament_banking.ps1` 运行现有主机精确回归及 21 个 layer2 co-sim，
再检查八个 score bank II=1、64-bit AXI、真实两个 tree 存储实例和 BuildTournament II。
资源 / 周期先与这一三 bank HLS 快照比较，收益以随后原生整帧及实际路由为准。
两 bank 若不满足端口 / 依赖门禁，再比较明确四 bank，不自动忽略失败。

第一阶段整帧收益仅 0.360% / 0.035%，资源明显增加，暂不选为新发布版。
保留这些已验证快照作为局部结构对照；继续减少资源开销，并优先实现描述子真实跨行
预取和方向矩加载融合，再推进完整 4PPC。旧 bitstream / GitHub main 保持原发布版本。
