# RK 转向断图诊断

本版本只增加观测，不修改匹配阈值、方向筛选、PnP/BA 接受条件、关键帧策略、
新建/合并地图规则、PL 特征算法或 bitstream。不启动 CPU ORB 回退。

在 RK 上位机中按正常流程开始新的摄像头建图。先平移建立稳定跟踪，再缓慢左右转向，
回到原来视角；如果出现第二张地图，可继续回看原场景以检验重定位/地图合并。
结束后保留本次 run 目录。无需为采集诊断修改摄像头或重烧 PL。

每个输入帧按原始帧号、纳秒时间戳写入
`runs/<session>/tracking/tracking_diagnostics.partNNNNNN.jsonl`：

- 原始 PL 特征数量、八层数量、32 档方向直方图。
- `tracking_enter/exit`：SLAM 状态、当前地图 ID、输入帧间隔。
- `motion_projection`、`bow_frame`：方向一致性筛选前/后的匹配数。
- `motion_result`、`reference_result`：各分支是否通过、匹配数及优化后的地图内点数。
- `local_projection`、`local_result/local_gate`：局部图投影匹配、几何内点数及接受条件。
- `relocalization_candidates/bow/pnp/optimized/result`：关键帧候选数、各阶段支持数及结果。
- `new_map/new_map_created`：旧/新地图 ID；原始 tracking.log 仍保留异步合并日志。
- 仅有效跟踪帧保存 Tcw，失效帧写 null；估计姿态不作为真实运动的测量基准。

未执行的阶段没有对应事件；-1 表示该分支尚未得到相应计数，不当作零个内点。
匹配次数计数沿用原算法的统计口径，不额外宣称一一对应的唯一点数量。
每帧最多 128 个事件、每个事件最多 24 个字段，超限记录 events_dropped；只记录
跟踪线程，不混入 LocalMapping/LoopClosing 并发匹配。每部分 3000 帧，保留最近四部分，
每 30 帧或状态改变时刷新缓冲。长会话早期诊断可能已按容量限制轮换，分析必须注明范围。

可在 RK workspace 目录汇总，或复制日志到电脑后使用同一命令：

```sh
python3 -m orb60.demo_bridge.summarize_tracking_diagnostics /path/to/run/tracking
```

输出 `tracking_diagnostics_summary.json`，包含状态/地图切换和掉跟踪前的事件窗口。
诊断用于区分搜索范围不足、方向筛选损失、几何剔除和重定位失败；仅有特征总数
不能证明描述子的旋转鲁棒性。

目标构建/部署由 `rk/build_tracking_diagnostics.sh` 执行：先做线程隔离、判定不变、
事件上限和实际 JSON/轮换自检，再串行构建，备份旧程序及库，切换独立 mapper 包。
只在没有活动建图/交接时重启 RK 控制服务；不开新会话，不重启 Zynq、不清地图。
`tracking_diagnostics_20261026/DEPLOYED.json` 是构建后部署记录；仅源码补丁成功不代表部署成功。
