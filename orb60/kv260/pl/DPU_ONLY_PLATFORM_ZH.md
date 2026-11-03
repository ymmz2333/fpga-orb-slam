# KV260 独立 DPU 硬件版本

本入口实现 KV260 的完整 DPU 顶层，不包含 ORB 图像核或描述子核。
它与原来的 `unified.tcl`、`orb_only.tcl` 分开保留。

2026-11-03 实板更新：该顶层是 **Vivado 原生 DPU 寄存器接口**，不能直接套用 Vitis/XRT kernel 的启动接口。早先 xclbin 元数据能注册、指纹能读回，但真实执行超时，失败证据保留。当前使用官方 linux-xlnx 2022.1 的 `xlnx_dpu` 驱动、`/dev/dpu` 和 VART 原生 DPU 控制器。20 张真实样本已实际执行并输出有效深度，执行中位数约91.13 ms；这包含显式 PS 辅助算子，不代表整机帧率。原始浮点精度门槛仍未通过，保持用户已接受量化模型的记录。

正确设备树入口是 `dpu_vivado_full_overlay.dts`（新启动后人工部署）；`dpu_vivado_driver_overlay.dts` 是本次从已加载诊断平台切换驱动的记录。`dpu_only_overlay.dts` 与手工 xclbin 仅保留诊断证据，不作为推理部署方案。驱动源码固定在 linux-xlnx 提交 `b0c1be301e78c320df8c4d93b18393bfd7fd4e9d`，本机副本为 `orb60/build/kv260_system/vendor_sources/xlnx_dpu_vivado_2022_1/`。模块必须对目标内核重新编译；本次 vermagic 为 `5.15.0-1027-xilinx-zynqmp`，不安装启动自加载规则。

预检显式选择 `--driver vivado`，通过 ioctl 重新读取真实指纹，并核对原有模型、系统和运行库约束。worker 从预检记录选择同一控制接口；不会因 XRT 失败自动改接口，也没有 CPU 卷积回落。

后续系统按用户确认的双板方案连接：

```text
7015：图像输入 → PL ORB → 特征、帧编号和时间戳 ──以太网──→ KV260 PS 建图
                       对应的 RGB 图像 ────────────────→ DPU MiDaS 深度
                                                          ↓
                                                 PS 对齐、赋色、融合
                                                          ↓
                                                  彩色点云 / GPU 显示
```

彩色稠密点云还需要与特征对应的 RGB 图像、相机内参和位姿，不能只传 ORB 描述子。
双板传输协议、重连、帧配对与整机性能属于后续集成；本次只生成独立 DPU 硬件。
以太网由 KV260 PS 上的 Linux 网络栈承担，本次没有在 PL 新增以太网协议核。

## 实现选择与配置

- DPU、ZynqMP PS、SmartConnect、MMCM、复位及中断：AMD IP。
- ORB-SLAM3 建图、地图管理、深度尺度拟合、点云筛选和融合：KV260 PS 软件。
- 深度网络：已编译的 MiDaS QAT 模型，DPU 执行卷积等受支持运算；显式的辅助运算仍由 PS 执行。
- 器件：`xck26-sfvc784-2LV-c`；板卡预设：`xilinx.com:kv260_som:part0:1.4`。
- 单个 `DPUCZDX8G 4.0 / ISA1 B4096`，目标指纹 `0x101000016010407`。
- 默认控制 / DPU / DSP 时钟：150 / 250 / 500 MHz。
  300 / 600 MHz 两次完整实现未满足 setup 时序，原始结果保留在交接记录中；
  每个版本是否通过仍以其 `validation.json` 为准。
- 56 个 UltraRAM；实际全部资源以本次完整布局布线报告为准。
- 官方 IP 来源及哈希：`orb60/build/kv260_system/vendor_sources/DPU_PROVENANCE.json`。
  官方发布参考工具为 Vivado 2022.1，本机实际构建使用 2024.2，兼容性以实际报告及后续板测为准。

## 连接

| 通路 | PS 接口 | 默认时钟 |
|---|---|---|
| 控制寄存器，128→32 位 SmartConnect | HPM0 | 150 MHz |
| DPU 指令，32→128 位 SmartConnect | HPC0 | 250 MHz |
| DPU 数据 0 | HP0 | 250 MHz |
| DPU 数据 1 | HP1 | 250 MHz |

DPU 的控制接口为完整 AXI4。HPM0 保留板卡预设的 128 位宽度，不照搬旧 AXI-Lite HLS 控制连接。
DPU 指令 ID 使用官方支持的 2 位，数据 ID 使用与 PS HP 端匹配的 6 位。
DPU 控制窗口为 `0xA1000000`、16 MiB，实际映射记录在 `address_map.tsv`。
DPU 中断接到 `pl_ps_irq0[0]`，其余 7 位接零；Linux 中断与设备树根据 XSA 核对。

## 构建

在 `D:\pld` 执行，Job 必须使用尚不存在的新目录名：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/kv260/pl/run_dpu_only.ps1 `
  -Job orb60/build/kv260_system/dpu_only_b4096_new -DpuMHz 250
```

脚本使用 `scripts/project_env.ps1` 获取环境；前台完成 IP 生成、综合、布局布线、完整静态检查，
通过后导出 `.bit`、`.bin` 和包含 bitstream 的 `.xsa`。不加载硬件，不修改启动文件。
源文件快照保存在 Job 的 `source_build/`，`.xpr` 入口写在 `project_path.txt`。

若已经完整 route，但报告或导出步骤因工具异常中断，可使用同一 Job 的 `-Mode reports`；
若静态检查已通过但导出中断，可使用 `-Mode export`。它们会保留新的源码快照，
导出前始终重新运行静态检查，不复用未经校验的旧通过标记。
已存在的 `source_reports/` 或 `source_export/` 不会被静默覆盖。

若完整布线后存在真实时序违例，可保留该失败 Job，再运行有边界的物理优化：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/kv260/pl/run_refine_dpu_only.ps1 `
  -BaseJob orb60/build/kv260_system/dpu_only_b4096_base `
  -Job orb60/build/kv260_system/dpu_only_b4096_refined
```

此操作从完整布线检查点开始，不改频率或时序约束；优化后重新生成全部报告和验收。
`refinement.json` 记录基础检查点哈希与实际命令。失败 Job 不会改写为通过。
物理优化版本的 `project_path.txt` 指向基础设计工程；最终实现请打开本 Job 的 `routed.dcp`：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/kv260/pl/open_dpu_only.ps1 `
  -Job orb60/build/kv260_system/dpu_only_b4096_refined
```

它先核对报告与产物，再打开准确的最终检查点，避免误看基础工程的旧时序。

## 验收与文件

`check_dpu_only.py` 保留完整顶层的时序、布线、覆盖率、资源、黑盒和 DRC 检查，
同时检查只有一个 DPU、没有 HLS 核，实际时钟与配置相符，生成的 DPU 指纹与冻结模型一致。
它不能用单核 OOC 报告或旧联合工程结果代替本次结果。
导出检查比较独立 bit 与 XSA 内 bit 的器件、设计信息和配置数据段；
Vivado 重新导出产生的日期／时间头字段单独保留，不参与配置数据等价比较。
每个完整文件仍分别记录 SHA256。

| 文件 | 用途 |
|---|---|
| `validation.json` | 完整顶层静态检查；失败时保留具体原因 |
| `release_manifest.json` | 导出检查、硬件和模型绑定、SHA256 清单 |
| `timing_summary.rpt` | setup、hold、pulse 和未约束路径 |
| `setup_paths.rpt` / `hold_paths.rpt` | 最差路径 |
| `utilization.rpt` / `utilization_hierarchical.rpt` | 完整顶层资源 / 层次资源 |
| `route_status.rpt` / `congestion.rpt` | 路由完整性 / 拥塞 |
| `drc.rpt` / `methodology.rpt` / `cdc.rpt` | 设计规则 / 实现方法 / 跨时钟 |
| `routed.dcp` | 完整布线检查点 |
| `dpu_arch.json` / `dpu_properties.tsv` | 官方生成架构 / 实际 IP 参数 |
| `kv260_dpu_only.bit` / `.bin` | 通过静态检查后导出的配置数据 |
| `kv260_dpu_only_with_bit.xsa` | 含同一 bitstream 的硬件交接文件 |

模型路径为 `orb60/build/kv260_system/depth_midas_qat/compiled/midas_kv260_b4096.xmodel`。
模型原数值门槛结果仍保留为 `QUANTIZATION_FAILED`，用户已明确接受视频视觉效果；
硬件静态通过不会把这个结果改写为数值通过。

静态检查通过使用 `FULL_TOP_STATIC_TIMING_PASS_BOARD_UNTESTED` 状态。
这不表示已经在 KV260 上执行 DPU 推理。上板仍需核对 XRT/VART、xclbin 元数据、
设备树、DPU 指纹、PS 时钟、DDR 与缓存一致性，然后运行真实 MiDaS 输入验证。
不以本轮主机布局布线推断实际 FPS。

## 交接包目录

`kv260_dpu_only_handoff.zip` 是硬件交接包，包含已验证硬件、生成脚本、选定模型和哈希清单。
`hardware/` 可用于检查结果和后续硬件交接；`source/` 按现有工程的目录结构排列，
可恢复到项目根目录，依赖原工程环境和已安装的 Vivado，不包含虚拟环境或工具安装程序。
新环境还需通过 `prepare_unified_vendor.py --download` 获取并核验官方 IP。
`model/` 是现有冻结模型与编译记录的副本；原工程使用说明中的模型路径不改变。
包内没有可直接启动的 SD 系统镜像，也没有宣称完成 Linux 驱动、xclbin 和双板通信部署。
