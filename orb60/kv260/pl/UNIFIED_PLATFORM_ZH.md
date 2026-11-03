# KV260 ORB＋DPU 统一硬件平台

这是 KV260/K26 的完整 PL 顶层构建入口。现有 ACZ7015 工程、ORB 单核 OOC、DPU 单独 overlay 都不能代替本工程。

## 实现选择

- 图像核和描述子核：保留已经通过 K26 CSim、综合、C/RTL 协同仿真及 64 位随机 AXI 验证的自定义 HLS IP；4PPC 图像核，150 MHz。
- 深度网络：AMD DPUCZDX8G 4.0，Vitis AI 2.5，单个 B4096，300 MHz AXI/逻辑时钟、600 MHz DSP 时钟。
- Zynq UltraScale+ PS、SmartConnect、MMCM、复位和中断拼接：AMD IP。
- ORB-SLAM3、地图管理、深度尺度拟合、点云融合：PS 软件；图形显示使用 PS Mali GPU。它们不消耗本报告里的 PL LUT。

目标器件 `xck26-sfvc784-2LV-c`，板卡预设 `xilinx.com:kv260_som:part0:1.4`。本机使用 Vivado 2024.2；DPU 发布时的参考工具是 2022.1，跨版本兼容性以实际 IP 生成、综合和完整布局布线证据为准。

## 连接与缓存

| 通路 | PS 接口 | 时钟 |
|---|---|---|
| ORB 图像 gmem0/gmem2、描述子 gmem0/gmem1 | HP2，4→1 SmartConnect | 150 MHz |
| ORB 图像 gmem1/gmem3、描述子 gmem2/gmem3 | HP3，4→1 SmartConnect | 150 MHz |
| DPU 指令 | HPC0 | 300 MHz |
| DPU 数据 0 | HP0 | 300 MHz |
| DPU 数据 1 | HP1 | 300 MHz |
| PS 控制三个计算 IP | HPM0 | 150 MHz |

上述接口访问同一块 PS DDR。不存在额外的 FPGA 内存槽 IP，也没有加入无必要的 DMA。

DPU 配置使用 56/64 个 UltraRAM（10 图像 bank＋17 权重 bank＋1 bias bank，每 bank 两个 URAM），避免默认 BRAM 配置挤占 ORB。实际资源以完整 routed top 为准。改变 URAM 分配不改变官方指纹表达式；仍要求生成的架构与已编译模型的 `0x101000016010407` 一致。

控制地址由设计生成器明确分配并由 Vivado 验证：

| IP | 地址 | 窗口 |
|---|---|---|
| ORB 图像核 | `0xA0000000` | 64 KiB |
| ORB 描述子核 | `0xA0010000` | 64 KiB |
| DPU | `0xA1000000` | 16 MiB，官方 IP 要求 |

中断按 DPU、图像核、描述子核依次接入 PS IRQ0 总线。运行配置和设备树必须与实际生成的 `address_map.tsv`、XSA 和板端中断映射核对，不能照搬 7015 的寄存器地址。

## 复现

在项目根目录执行，`-Job` 每次使用新的目录名：

```powershell
.venv/Scripts/python.exe orb60/kv260/pl/prepare_unified_vendor.py --download
powershell -ExecutionPolicy Bypass -File orb60/kv260/pl/run_unified.ps1 `
  -Job orb60/build/kv260_system/unified_b4096_new
```

Vivado 工程在 `scripts/project_env.ps1` 定义的 scratch 下，构建目录中的 `project_path.txt` 给出本次 `.xpr`。编译在前台执行，日志保存在 `console_build.log`。源 Tcl 快照保存在 `source_build/`，DPU 来源及哈希在 `vendor_sources/DPU_PROVENANCE.json`。

完整 route 后重新打开 checkpoint 做审计，再执行严格检查：

```powershell
. ./scripts/project_env.ps1
$env:KV260_UNIFIED_JOB=(Resolve-Path orb60/build/kv260_system/unified_b4096_new).Path
& $VivadoBat -mode batch -nojournal -nolog -source orb60/kv260/pl/audit_routed.tcl
.venv/Scripts/python.exe orb60/kv260/pl/check_unified.py $env:KV260_UNIFIED_JOB
```

`validation.json` 只有在完整报告、正确器件/指纹、所有可布线网络完成、无 black box、无 DRC Error/Critical Warning、无未约束端点，且 setup/hold/pulse 均通过时才允许写入 `FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED`。

## 报告入口

- `timing_summary.rpt`：完整顶层 setup/hold/pulse、TNS、失败端点及未约束检查。
- `setup_paths.rpt`、`hold_paths.rpt`：最差路径，分析逻辑、布线及跨时钟关系。
- `utilization.rpt`、`utilization_hierarchical.rpt`：完整顶层资源及模块分布。
- `route_status.rpt`、`congestion.rpt`：路由完整性、布线错误、拥塞。
- `drc.rpt`、`methodology.rpt`、`cdc.rpt`、`clock_interaction.rpt`：设计规则、实现方法、跨时钟检查。
- `routed.dcp`：完整布局布线 checkpoint，可在 Vivado 中打开查看 Device 和 Timing。
- `kv260_orb_dpu.xsa`：完整平台硬件交接，当前构建不自动烧写，不包含启动系统更新。

静态时序通过也不代表实际 DPU、共享 DDR、Linux 设备树/XRT/VART 或 ORB＋深度同时运行已经通过。板端测试之前，不能发布单板实际 FPS 或整机实时结论。
