# FPGA全景项目开发与工具指南

## 1. 目录与环境约定

`D:\pld` 是唯一开发根。源码、测试、文档和保留报告在这里；Vivado/XSIM临时
工程默认位于 `D:\pld\.work\vivado`，兼顾短路径和统一管理。根目录的 `.venv`
必须由 `scripts\bootstrap.ps1` 在本地创建，不能从旧项目复制。

统一入口 `scripts\project_env.ps1` 支持下列覆盖变量：

| 变量 | 用途 | 本机默认值 |
|---|---|---|
| `FPGA_VIVADO_ROOT` | Vivado根目录 | `D:\Xilinx\Vivado\2024.2` |
| `FPGA_VITIS_HLS_ROOT` | Vitis HLS根目录 | `D:\Xilinx\Vitis_HLS\2024.2` |
| `FPGA_VITIS_LIBRARIES_ROOT` | Vitis Libraries | `D:\Xilinx\Vitis_Libraries\2024.2_update3` |
| `FPGA_MODELSIM_BIN` | ModelSim/Questa可执行目录 | `C:\modeltech64_2020.4\win64` |
| `FPGA_MODELSIM_LICENSE` | ModelSim许可证 | 上述目录的`LICENSE.TXT` |
| `FPGA_BASE_PYTHON` | 创建venv的Python | CPython 3.12.12 |
| `FPGA_VIVADO_BUILD_ROOT` | Vivado/XSIM短路径临时根 | `D:\pld\.work\vivado` |

只在当前PowerShell加载环境：

```powershell
. .\scripts\project_env.ps1
.\scripts\check_environment.ps1 -RequireAmd -RequireModelSim
```

## 2. 工具各自负责什么

| 工具 | 本项目用途 | 不能证明什么 |
|---|---|---|
| Python/OpenCV/NumPy | 独立黄金模型、定点模型、RANSAC、拼接和指标 | 不能证明RTL接口与器件时序 |
| cocotb | 复位、随机valid/ready、AXI DDR、边界和错误注入 | 大视频逐拍驱动较慢 |
| Icarus | 小型RTL快速事件仿真与VCD | 不适合部分HLS存储器和大批量 |
| 原生Verilator | 多帧、数百万周期、生成RTL的大批量回归 | 不支持所有AMD加密/行为模型 |
| Yosys | 早期结构、资源趋势和明显组合深度 | 不代替XC7Z020布局布线 |
| GTKWave/WaveTrace | 查看VCD/FST波形 | 波形看起来合理不等于自动核验通过 |
| Vitis HLS | C++/pragma到RTL、CSim、综合、C/RTL co-sim | HLS估算不等于post-route结果 |
| Vitis Vision | 标准视觉算子的候选实现 | 官方函数不保证本器件资源/时序最优 |
| Vivado | AMD IP、综合、布局布线、资源/时序/DRC签核 | 不能替代独立功能黄金模型 |
| XSIM | 真实DMA、SmartConnect、PS7相关AMD模型集成 | 事件仿真速度不代表实机速度 |
| ModelSim 2020.4 | cocotb调用Vivado导出的IP/原语模型 | 版本与编译库必须匹配 |

## 3. 分层开发命令

### 3.1 手写RTL单元

```powershell
.\.venv\Scripts\python.exe .\run.py --test fast9
.\.venv\Scripts\python.exe .\run.py --test nms
.\.venv\Scripts\python.exe .\run.py --test fast9_nms_pipeline
.\.venv\Scripts\python.exe .\run.py --test feature_frontend
```

改动接口时必须包含复位中断、随机背压、连续帧和边界尺寸。大批量不要让Python
每拍驱动，使用 `panorama\run_pl_panorama.ps1` 或
`panorama\run_multi_ip_batch.ps1` 里的原生Verilator testbench。

### 3.2 HLS核

```powershell
.\panorama\hls_orb_list_descriptor\run.ps1
.\panorama\hls_orb_list_descriptor\run_vivado.ps1
```

顺序不可省略：独立Python golden → CSim → C综合报告 → C/RTL co-sim → 生成RTL
cocotb随机AXI → Vivado OOC。优化应修改C++数据结构、定点位宽和pragma，不得修改
`solution*/syn/verilog`。如果保留125 MHz版本，应把HLS目标周期同步改为8 ns后重新
生成OOC checkpoint。

### 3.3 多IP快速整机

```powershell
.\panorama\run_multi_ip_batch.ps1
```

它在一个共享DDR模型中运行真实FAST/NMS、HLS描述子、RTL Hamming和控制胶水，
随后由PS软件生成全景。只有需要验证完整连接或最终图像时运行；只改FAST内部
流水线且14帧候选bit-exact时，无需重复耗时最大的Hamming穷举。

### 3.4 AMD IP/XSIM集成

```powershell
.\panorama\vivado_multi_ip\run_xsim.ps1
```

此层保留真实AXI DMA、SmartConnect、Width Converter和HLS IP，用小图核对寄存器
编程、DMA长度、逐行TLAST、仲裁和连续两帧。默认前台运行，Agent应保留终端并
每隔不超过约60秒检查一次。

### 3.5 完整布局布线

```powershell
.\panorama\vivado_multi_ip\run_build.ps1 -FrequencyMHz 100
.\panorama\vivado_multi_ip\summarize_reports.ps1 -FrequencyMHz 100
.\panorama\vivado_multi_ip\run_build.ps1 -FrequencyMHz 125
```

100 MHz是硬门槛和稳定基线，125 MHz是性能档。签核必须同时检查setup/hold、
unconstrained path、DRC、全部网络是否布通、关键路径逻辑级数/布线占比、拥塞与
层次资源。不能只引用综合估计或OOC核心合计。

### 3.6 Vivado IP + ModelSim + cocotb

```powershell
.\vivado_ip_demo\run_modelsim.ps1
```

脚本只设置 `MGLS_LICENSE_FILE` 给ModelSim，不覆盖通用 `LM_LICENSE_FILE`，从而
避免与Vivado许可证冲突。GUI波形使用 `-Gui`。

## 4. 选择PS、AMD IP、HLS还是RTL

- 非规则控制、图优化、RANSAC、Homography和Blend优先PS软件。
- DDR控制、SmartConnect、DMA、时钟、复位和成熟协议优先AMD IP。
- 规则循环、卷积、描述子和可定点化算法优先HLS原型，再用报告决定是否保留。
- 位级归约、严格握手、小型高频数据通路和已证实HLS热点适合手写RTL。
- 不确定时实现两个有边界的最小版本，对同一器件和时钟比较功能、周期、资源、
  post-route时序与开发风险。

## 5. 高频故障与处理

### 旧绝对路径或路径过长

复制来的 `.xpr`、`hls.app`、日志、status JSON和已编译库可能保留旧路径，它们是
历史产物，不要逐个手改。使用新根目录脚本重新生成。HLS/ModelSim长模块名容易
触发Windows路径限制，临时工程保持在 `.work` 或短的stage目录。

### Python版本/ABI混用

始终调用 `.venv\Scripts\python.exe`。Vivado修改PATH后可能选中自带旧Python；
脚本必须使用显式项目解释器。迁移后禁止复用旧 `.venv`。

### cocotb + Verilator在Windows链接失败

如果最后出现找不到 `-lcocotbvpi_verilator`，通常是Perl/MinGW和cocotb动态库ABI
混用，不是RTL错误。小协议测试继续用cocotb+Icarus；大批量使用原生Verilator
HDL testbench和独立Python post-check。

### 组合逻辑太深

功能仿真不会因为逻辑级数深而自动失败。以Vivado post-route critical path为准，
在真实热点增加流水、平衡归约树或处理扇出，随后重跑功能门禁。不要凭源码猜，
也不要在所有AXI接口盲目插寄存器。

### HLS“像普通C++”导致差结果

先定义接口、位宽、访问模式、II和缓存，再写规则循环、局部窗口、定点数和pragma。
关注II未达标、burst/widen失败、隐式大位宽、完全展开、随机DDR访问和巨型选择器。
厂商Vision函数必须和手写基线做真实资源/时序比较。

### AXI/DDR集成问题

- VALID/DATA必须保持到READY；随机停顿必须覆盖。
- FAST需要逐行TLAST，DMA帧末TLAST需要framer转换。
- 当前候选S2MM最大65,544字节，DMA length width不能使用14位默认值。
- Zynq-7000地址使用32位；burst不得跨4 KB边界。
- 零候选、8192候选、溢出、空训练表、复位中断和连续帧都要测试。
- BRAM是片上存储资源，DSP是运算资源，不是需要软件模拟的外设；DDR/AXI模型
  负责外部存储事务，DMA只在流与内存边界需要。

### “通过”的含义混淆

CSim、C综合、co-sim、cocotb、Verilator/Yosys、OOC、顶层route各自只回答一个
问题。任何post-check失败都是真失败；能综合不等于功能正确，单IP WNS为正也不
等于整机通过。

## 6. 暂不上板时的证明边界

电脑端可以证明算法bit-exact、AXI协议、共享DDR争用模型、完整资源、布局布线
时序和理论带宽。它不能证明实际DDR初始化与持续带宽、PS缓存一致性、Linux驱动、
实时视频输入、板上功耗温升和物理I/O。这些必须作为将来的上板门禁明确保留。

