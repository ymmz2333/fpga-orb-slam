# PL 综合与 Vivado 2018.3 迁移

2026-10-23，用户授权开始综合，并因本机没有 Vivado 2024.2，明确要求改为 2018.3 工程。此前“不综合”的限制已由这次指令更新。首轮只做综合，后续按继续指令完成时序修正、布局布线、bitstream 和 HDF 导出；尚未加载新 PL 或修改 SD 启动文件。各阶段历史记录如下。

PL 目标仍为 `xc7z015clg485-2` / `s_wrapper`，ORB 4PPC、150 MHz，PS FCLK0 100 MHz，AXI-Lite 地址 `0x43c00000` / `0x43c10000`，控制寄存器切片模式 7。建图、定位、地图管理和软件 UI 是 PS 端 C++ 程序，不通过 Vivado 综合；摄像头和 HDMI 新硬件通路仍待集成。

从本工程目录运行：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/synth_pl_2018.py --mem2-slices
```

脚本校验冻结交接包的原始 Tcl、PS 配置和两个 IP ZIP 的 SHA-256，检查 ZIP CRC 后解包到 `../.work/z18/时间戳/`。保留原连接和参数，去除原脚本的全部实现步骤，使用 `xilinx-2018.3.cmd` 启动 Vivado 2018.3。综合作业和工具线程均为 1，不更改全局 PATH。`--prepare-only` 仅准备输入，不启动 Vivado。

原 HLS RTL 由 2024.2 导出，本轮复用其导出 RTL，未重新运行 HLS。该导出 RTL/IP 已通过 2018.3 的新综合；源 HLS C++ 在 2018.3 HLS 中重新生成仍未验证。历史 2024.2 的资源、时序和板测证据不能作为迁移后的验收结论。冻结交接包、u1、原 bit/ELF 均保留。

每次运行独立目录保存 `status.json`、原始输入哈希、`staged_ip_hashes.json`、`synth_only.tcl`、`version.log`、`console.log`、`vivado.log` 和工程目录 `vivado/`。只有返回码为 0、综合成功且无未解析黑盒，并写出 `vivado/SYNTHESIS_COMPLETE.txt` 时，脚本才记录 PASS。综合后将保存资源、时序估计、时钟、约束覆盖、DRC 和 IP 状态报告；这些报告不代表布线后收敛或持续 30 FPS。

IP 输出文件生成后，可运行 `fpga-python.cmd scripts/check_pl_contract.py ../.work/z18/运行目录` 检查生成配置与软件接口：原控制地址、四个 HP 端口、时钟、DDR 频率、传播得到的低有效复位、寄存器切片和全部导出 IP 文件哈希。检查结果写入运行目录的 `contract_check.json`。

首个实际综合运行目录为 `../.work/z18/20261023_093417/`，对应 `vivado/p.xpr`。之前三个运行目录仅保存启动器检查失败的日志，未进入综合。当前运行的只读参数写入提示已核查：复位生成值为 0、极性 ACTIVE_LOW，PS FCLK 为 100 MHz；工具通过连线传播派生值。AXI ID/LOCK 宽度提示仍保留，需要结合综合结果和后续总线仿真检查，不能据此声称硬件功能验收。

首个运行已于 10:13:55 完成综合，17 个 IP 子任务和顶层成功、没有未解析黑盒；12 个顶层 IP 状态均为 Up-to-date。资源为 LUT 37,391（80.93%）、寄存器 37,781（40.89%）、BRAM 71.5（75.26%）、DSP 44（27.50%）。综合时序估计 WNS −0.366 ns、TNS −3.610 ns、10 个 setup 违例端点，WHS +0.029 ns，约束覆盖检查的问题数量为 0。`status.json` 的 PASS 表示综合流程完成，不能解释为时序通过；`review.json` 将两者分别记录。

13:35 对原综合网表补充只读分析，保存在该目录的 `inspection_20261023_133540/`：10 条负 slack 路径均涉及 mem2 的 AXI 写反压长链；方法学报告有 12 项 LUTAR-1 警告，没有 TIMING 类报告项。DRC 报告列出 89 项警告，其中两个 CHECK-3 表明 REQP-1839/1840 达到每规则显示上限，不能将 89 当成完整真实总数。未创建 waiver 或修改时钟约束。

针对上述长链，`--mem2-slices` 在 mem2 的 S00/S01 侧启用厂商 Outer Register Slice（S00_HAS_REGSLICE=1、S01_HAS_REGSLICE=1），维持原时钟、地址、算法和描述子 RTL。切片增加总线事务延迟，后续仍须验证背压与复位。新候选运行是 `../.work/z18/20261023_133841/`，使用下列命令独立综合：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/synth_pl_2018.py --mem2-slices --ip-cache ../.work/z18/20261023_093417/vivado/p.cache/ip
```

`--ip-cache` 将旧运行的 2018.3 IP 缓存复制到新运行后复用，不写回原缓存。当前生成脚本还省略了首个运行已经证实为只读或不允许改写的 PS 配置项，复位极性通过连接传播，并由独立配置检查确认。候选生成配置已通过 29 项检查，642 个原始 IP 文件哈希保持一致；最终时序和资源以候选运行的新报告为准。

报告命令：`fpga-python.cmd scripts/report_pl_2018.py ../.work/z18/运行目录`，生成 `review.json` 和 `REVIEW_ZH.md`。`analyze_pl_2018.py` 只读打开综合检查点，导出负 slack 路径、方法学报告和约束，不执行实现。

13:45:30，带 mem2 输入切片的候选综合完成。综合后 setup WNS +0.114 ns、TNS 0、违例端点 0；hold WHS +0.029 ns、THS 0；脉宽 WPWS +2.203 ns。没有未解析黑盒，12 个顶层 IP 均 Up-to-date，约束覆盖问题计数均为 0。29 项配置检查和 642 个导出文件哈希检查再次通过。

| 指标 | 原迁移拓扑 | mem2 输入切片拓扑 |
| --- | ---: | ---: |
| WNS / ns | −0.366 | +0.114 |
| TNS / ns | −3.610 | 0 |
| setup 违例端点 | 10 | 0 |
| LUT | 37,391（80.93%） | 37,487（81.14%） |
| 寄存器 | 37,781（40.89%） | 38,219（41.36%） |
| BRAM Tile | 71.5（75.26%） | 71.5（75.26%） |
| DSP | 44（27.50%） | 44（27.50%） |

新增切片使 LUT 增加 96、寄存器增加 438。建议后续使用 `--mem2-slices` 重建上述拓扑。候选中的配置只读写入 Critical Warning 已去除；常规 ID/LOCK 位宽和工具 IOPAD 提示仍保留。DRC 报告仍列出 89 项警告，涉及 DSP 流水线及 RAM 异步控制，包含相同的报告数量上限提示，未做 waiver。

这次通过的是综合和综合后估计，不是布局布线验收。摄像头／HDMI 硬件通路、PS 软件 ARM 部署、复位与 AXI 背压、输出一致性及持续整机 30 FPS 仍需验证。

13:47 对保存后的候选检查点再次只读检查，`inspection_20261023_134547/` 中的负 slack 路径报告显示 No paths found；方法学报告仍为 12 项 LUTAR-1 Warning，没有 TIMING 类项目，未创建 waiver。该独立分析返回码为 0。当前没有运行中的综合或实现任务。

15:55 启动布局布线，从上述已通过复核的候选综合结果继续，策略 `Performance_Explore`，Vivado 2018.3，一个作业／线程，仅运行到 `route_design`：

```powershell
& 'C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/fpga-python.cmd' scripts/route_pl_2018.py ../.work/z18/20261023_133841
```

该命令拒绝过期综合结果和覆盖已有实现。它在生成的 `vivado/p.xpr` 中使用尚未启动的 `impl_1`，保留既有综合报告和检查点；实现报告写入 `../.work/z18/20261023_133841/route_20261023_155531/`。`FLOW_COMPLETE` 只表示 route_design 流程完成，时序、布线完整性、约束覆盖、实际 Slice 等资源以及 DRC 需另行复核。

复核命令为 `fpga-python.cmd scripts/report_route_2018.py 实现报告目录`，独立生成 `review.json` 和 `REVIEW_ZH.md`。后续以布线报告为准，不使用综合估计代替实际时序。此阶段不生成 bitstream、不访问 JTAG；摄像头／HDMI 新硬件通路和 PS 软件仍不在当前 PL ORB 实现范围内。

16:22:01，Vivado 2018.3 完成该次实现和最终检查点保存，进程返回码 0；独立报告复核为 PASS：

| 布线后指标 | 结果 |
| --- | ---: |
| Setup WNS / TNS | +0.029 ns / 0 |
| Hold WHS / THS | +0.023 ns / 0 |
| Pulse width WPWS / TPWS | +2.203 ns / 0 |
| Setup／hold／脉宽违例端点 | 均为 0 |
| 完全路由／可布线网络 | 63,827 / 63,827 |
| 布线错误 | 0 |
| Slice | 11,447 / 11,550（99.11%） |
| LUT | 35,761 / 46,200（77.40%） |
| 寄存器 | 37,228 / 92,400（40.29%） |
| BRAM Tile | 71.5 / 95（75.26%） |
| DSP | 44 / 160（27.50%） |

PS FCLK 100 MHz、ORB 150 MHz 的时钟与约束覆盖检查通过，非零覆盖问题项为 0。DRC 为 86 个报告项，均为 Warning：DPIP-1 13、DPOP-1 4、DPOP-2 30、REQP-1839 19、REQP-1840 19、RTSTAT-10 1。RTSTAT-10 项覆盖 63 个无可布线负载的内部网络；布线完整性用上述 route_status 单独核对。方法学仍有 12 项 LUTAR-1 Warning，没有 TIMING 类项目；未创建 waiver。

最终产物在 `route_20261023_155531/`：`s_wrapper_routed.dcp`、`post_route_*.rpt`、`completion.tsv`、`status.json`、`review.json`、`REVIEW_ZH.md`。这是当前 PL ORB 的实现验收，尚未生成 bitstream 或烧板。Slice 余量仅 103 个，后续摄像头／HDMI 通路必须重新核算资源和时序空间；PS 建图／定位／UI、接口功能及整机持续 30 FPS 仍待验收。

17:07 前，`bit_20261023_165856/` 完成 bitstream 与 SDK 2018.3 HDF/hwdef 导出，返回码 0、导出校验 PASS。命令为 `fpga-python.cmd scripts/bit_pl_2018.py ../.work/z18/20261023_133841/route_20261023_155531`。脚本核对已验收的报告和 DCP 哈希，只继续 impl_1 的 write_bitstream；原实现检查点哈希保持不变，复核 setup +0.029 ns、hold +0.023 ns，无 Error/Critical Warning DRC，HDF ZIP CRC 及嵌入 bit 与独立 bit 一致。

| 导出 | 字节数 | SHA-256 |
| --- | ---: | --- |
| s_wrapper.bit | 3,510,773 | 25902e96161587818f7c8de3c28ce57ef1c3e3b83ced57897a353f234dbc010e |
| s_wrapper.hdf | 1,544,170 | be3201f4861655a2722cbb2e4710ae73b80729f4a856205554a8b488bbf9c93d |
| s_wrapper.hwdef | 351,791 | c5198d3cd38774eeca545960dcbe0922f997195a76378b0004c0eefa95046526 |

HDF 包含 PS 初始化 C/H/Tcl、硬件说明、匹配 bit 和原 IP 驱动。SDK 2018.3 GCC 7.3.1 已交叉编译 PS 应用及自测。`package_sd_ssh.py` 通过 Bootgen 2018.3 生成 `.bit.bin`，验证换序配置负载和 NOP 补齐；上传包和 ARM 纯软件自测走 SSH，不改变现有 SD BOOT.BIN/system.bit/设备树。此段为17:07时的ORB-only历史结果。

## 最终 HDMI_2 顶层（20:11导出，取代上述ORB-only产物）

摄像头不在本轮接入范围。原生TMDS扫描、异步FIFO、共享HP3和视频寄存器合入完整s_wrapper后，使用相同Vivado2018.3/器件重新综合及布线。最终综合`../.work/z18/20261023_194328`，布线`route_20261023_195215`的独立review.json全部11项PASS。Setup WNS+0.015ns/TNS0，Hold WHS+0.013ns/THS0，脉宽余量1.101ns；66068/66068网全部路由，0布线错误。Slice11523/11550（99.77%）、LUT36777、FF38422、BRAM73.5/95、DSP44。

ORB150MHz，HDMI像素74.25MHz/串行371.25MHz，PS FCLK0仍为100MHz。内部时序覆盖完整；4个TMDS正端序列化外部边界缺少PCB/接收器模型而单列，未捏造output_delay。Gray总线skew通过，CDC无Warning/Critical，DRC/方法学无Error/Critical，普通异步RAM/DSP等Warning保留在原报告中。

最终导出目录`../.work/z18/20261023_194328/final_20261023_201146`含bit/HDF/hwdef，ZIP CRC及HDF内嵌bit逐字节匹配。此版已通过SSH RAM加载、物理ORB逐字节验证和HDMI_2点云显示。此后性能改动仅在PS软件，未重新改动此版RTL。完整仿真、I/O与整机记录见`HDMI_IMPLEMENTATION_ZH.md`，SD启动操作见`SD_SSH_ZH.md`。
