# KV260 DPU＋点云投影核

## 当前有效部署路径（2026-11-03，阶段S）

干净启动后已实际验证：从同一份已布线 checkpoint 导出带
`BITSTREAM.CONFIG.USR_ACCESS=0x4F525050` 的配置，清零 FPGA manager
`flags` 后使用 firmware 文件加载，通过 **PCAP配置寄存器** 确认实际 K26
IDCODE 和配置标识，再应用 `interfaces.dtbo`、绑定匹配内核的原生 DPU 驱动。
对应源码为 `prepare_tagged.py`、`export_tagged.ps1`、`prepare_phased.py`、
`deploy_phased.py` 和 `config_identity.py`。`firmware.dtbo` 保留供检查，当前加载
流程不使用它；不能用 configfs 的 `applied` 或 manager 的 `operating` 单独证明
实际加载的是目标位流。

本机匹配内核的头文件定义 `FPGA_MGR_CONFIG_DMA_BUF=BIT(8)`；启动后曾读到
`flags=0x100`。新文件加载流程显式清零该标志并记录前后值。先前失联阶段缺少完整
最后状态，因此只记录已验证的修正，不追认每次历史故障的确切原因。

当前缓冲选择为显式 `memory_backend=native-dpu`，使用匹配 `xlnx_dpu` 驱动的
DMA 分配和缓存同步接口；**不添加额外 zocl/XRT 分配器设备节点**。早期额外节点
触发内核异常的候选已撤回。下文提及 XRT BO 的内容描述旧候选，不作为本次加载入口。
驱动不会自动回退到CPU投影，不读取任意物理DDR地址。

阶段S的实际平台回读、点核四组测试、DPU指纹/配置检查通过。首个真实关键帧
146,249点与独立参考比较通过，RGB、像素索引、点顺序一致，最大坐标绝对误差
`1.1920928955078125e-07`。完整2297帧DPU和点核链已运行，但地图连续性失败，
不能作为整机通过。证据位置与最新结果见上级 `TWO_BOARD_MIGRATION_ZH.md`。

## 2026-11-03 主会话实测增量

本轮已在 KV260 加载完整 DPU＋点云平台，实际点核地址为 `0xA2000000`。
四组板上测试（正常6点、空输入、容量1、容量0）通过，分别写入2、0、1、0点。
这不代表整段视频、地图连续性或30FPS通过。

当前明确选择 `point_memory_backend=native-dpu`：复用已安装官方 `xlnx_dpu`
驱动的连续内存分配／映射／缓存同步接口，仍由独立 UIO 控制点核，没有CPU投影回退。
`native_memory.py` 只映射本实例申请的内存，不使用 `/dev/mem` 或预留物理地址。
在 VART 启动前申请、VART 退出后释放，避免该保留驱动无锁全局分配链表的并发增删。

XRT 仅分配缓冲的尝试失败：注册检查触发 `kds_init_client` 内核Oops并影响 Xorg。
该设备已解绑，不允许把元数据生成成功当成板上成功。
`dpu_points_firmware_20261103_d` 删除了额外 DRM/XRT 节点，作为后续加载资产。
`build_metadata.py` / `register_allocator.py` 仅保留失败分支的复现入口，当前板不使用。
固件与驱动没有修改开机配置；重启后必须重新核验并显式加载，旧 preflight 不代表新启动状态。

`dense_service.py` 与 `run_network_system.py` 现在支持显式 `point_backend=pl`、
`point_memory_backend=native-dpu`、`point_uio`、`point_abi` 和 `point_preflight`。
第一份真实关键帧投影会与独立双精度模型核对坐标、RGB、像素索引和顺序。
后端仍由 PS 完成拟合、多视角筛选、体素融合及最终位姿修正。

完整视频首轮复测因桌面会话失败在72帧中止，未得到整段地图结论。
新加的 `map_continuity.py` 检查全部Atlas创建事件和逐帧丢失区间；
中途新建地图即失败，即使最后导出仅剩一张地图也不会隐藏。
之前 `defer-strong` 跟踪候选在第763–907源帧丢失并新建map1，已撤回，后续恢复原始求解流程。

以下章节保留原硬件设计和早期入口说明；涉及XRT的描述是早期接口设计，当前保留路径以上述原生DPU内存接口为准。

这是用户授权的独立硬件增量，不改当前主会话的无压缩输入和原融合入口。
工程位置 `D:/pld/orb60/kv260/point_pl/`。实现选择：规则逐点计算用自定义 HLS；
PS、DDR 接口、SmartConnect、时钟和复位用 AMD IP；地图管理、深度拟合、体素合并用 PS。

## 实际覆盖范围

```text
DPU 相对逆深度
  → PS：去畸变／缩放、稀疏观测拟合尺度与偏移、生成深度和掩码，打包每隔2像素的样本及RGB
  → PL：反投影 → 相机局部XYZ → 世界XYZ，附带样本RGB，过滤无效点
  → PS：多视角一致性、体素合并、点块管理和后续位姿修正
```

本核不代替整个 `Fusion.process()`，也不加速 ORB-SLAM3 的 BA。
它不会消除当前全部 1.4–2.7 秒融合开销；整体收益必须按真实输入计入打包、缓存同步和输出复制重新测量。
FP32 计算与原 PS 双精度有舍入差异，验收容差为 `atol=3e-5, rtol=3e-5`；
颜色、源像素索引、顺序、计数和错误状态必须精确一致。体素边界可能因 FP32 舍入产生少量分组差异，不能宣称最终 PLY 逐字节相同。

## 缓冲 ABI（小端）

- 输入每点16字节：`float32 depth; uint32 R|G<<8|B<<16; uint32 u|v<<16; uint32 mask_bit0`。
- 配置96字节：24个float32，前9个为 `inverse(K)` 按行，接着12个为 `Twc[:3,:4]` 按行，最后3个保留0。
- 输出每点32字节：6个float32，依次相机局部XYZ和世界XYZ，然后RGB uint32、`v*960+u` uint32。
- 状态32字节：`seen, valid_total, written, errors, 0x50434c31, 1, 0, 0`。
- 最大输入和输出容量172800点；稳定压缩输出保留输入顺序。
- 错误位：1=容量不足，仍统计所有有效点；2=count/capacity越界，禁止读样本和写点；4=非有限配置。
- 掩码为0、深度非有限／非正、像素越界、坐标计算非有限的样本被过滤。
- 常规 SLAM 相对坐标、相机内参和深度是数值验收范围；不宣称支持任意极端／非规格化浮点数。
- 指针为64位；CPU 与 PL 通过 XRT 管理的 BO 交接，必须同步缓存。输入输出不得重叠。

寄存器名称和偏移从实际 HLS 头文件生成 `point_abi.json`，不能凭旧 ABI 推断。
本版 HLS 将配置指针名称生成 `CONFIG_R_DATA`。控制基址 `0xA2000000`、64KiB。

## 硬件组合

新平台 DPU B4096：250MHz、DSP500MHz，控制和点云核150MHz。
DPU 指令走 HPC0，数据走HP0/HP1；点云输入和输出通过2→1 SmartConnect共用HP2。
所有主设备访问同一 PS DDR，不额外增加 DMA，不使用额外 URAM 缓存全帧。
点云核 CSR 是 AXI-Lite，由控制 SmartConnect 做协议适配。
中断总线 bit0=DPU，bit1=点云核；当前驱动采用轮询，不启用点云核 GIE。
不能把此前 DPU-only 的 bitstream 与这个核分别加载，必须使用新的统一实现。

## 验证与构建

依次执行独立 Python golden、C仿真、综合、C/RTL协同仿真、随机AXI／复位／边界检查、OOC、完整顶层实现。
已有命令入口为 `run_hls.ps1`、`build_simlib.py`、`run_axi.py`、`ooc.tcl`、`run_system.ps1`。
环境一律加载 `scripts/project_env.ps1`。每次 Job 使用新目录，不覆盖失败记录。
HLS 和 OOC 的资源／时间不是完整系统结果，更不是板端 FPS。

在项目根目录使用两个入口重建，前缀与Job必须全新：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/kv260/point_pl/run_components.ps1 -Prefix orb60/build/kv260_system/points_NEW
powershell -ExecutionPolicy Bypass -File orb60/kv260/point_pl/run_system.ps1 `
  -Job orb60/build/kv260_system/dpu_points_NEW `
  -Hls orb60/build/kv260_system/points_NEW_hls `
  -Protocol orb60/build/kv260_system/points_NEW_axi `
  -Ooc orb60/build/kv260_system/points_NEW_ooc
```

内部 `simlib.tcl` 仅保留早期目录选择失败的诊断尝试，不作为有效构建入口。

## 主会话使用

主会话已新增配置资产生成入口，使用全新输出目录：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/kv260/point_pl/prepare_firmware.ps1 `
  -Job orb60/build/kv260_system/dpu_points_250_150_20261103_a `
  -Output orb60/build/kv260_system/dpu_points_firmware_NEW
```

它核验本次完整导出、DPU与点核地址以及共享DDR映射，调用Bootgen生成Linux所需的`.bit.bin`，
按字节核验原配置载荷的32位字交换，并编译／回读合并点核UIO节点的设备树。
成功状态`MATCHED_FIRMWARE_DT_PREPARED_BOARD_UNTESTED`只证明配置资产准备完成；
不加载硬件、不修改启动文件，也没有代替新XRT元数据核对和实际板端预检。
当前已生成的`dpu_points_firmware_20261103_b`保留Bootgen／DTC日志，尚未加载。

完成新的平台部署和实际小样本核验后，再生成板端 preflight，驱动才允许执行。
`runtime.Projector` 要求显式 UIO 路径、匹配 ABI 和 `DPU_POINTS_BOARD_PREFLIGHT_PASS`，
禁止默默使用 CPU 投影，也不自动加载 FPGA 或修改启动文件。
`point_uio_fragment.dtsi` 只是合并节点示例，必须与新 XSA、现有 DPU/xclbin 部署脚本一同核对。

`fusion.PlFusion` 继承当前 `Fusion`，仅覆盖 `_publish()` 中的点生成，保留多视角检查、地图隔离、
局部点块、体素管理及 `update_pose` / `finalize`。主会话可显式选择这个类：

```python
from orb60.kv260.point_pl.runtime import Projector
from orb60.kv260.point_pl.fusion import PlFusion
projector = Projector(uio_path, abi_file, board_preflight_file)
fusion = PlFusion(block_folder, publish, backend_label, projector=projector, voxel_class=voxel_class)
```

退出时关闭 projector。发生超时或状态异常后拒绝继续复用；需核对并恢复平台。
若核尚未空闲，close也会拒绝释放其XRT缓冲；须先停止／恢复平台，不能直接复用这片DDR。
这不是自动故障恢复机制；若进程异常退出，缓冲生命周期还受驱动影响，加载端必须负责停核／复位后的恢复流程。
板端必须对真实关键帧比较点数、RGB、坐标误差、多视角筛选和最终点云差异，再测整链吞吐。
本次电脑验收不等于新点云核已完成板端执行。

`board_smoke.py` 提供实际加载后的四组点测试：正常输入、空输入、输出不足和零容量。
它不写 FPGA、不改设备树，需要加载端先提供 `deployment_receipt.json`，字段为：
`status=DPU_POINTS_LOADED`、`bitstream_sha256`（必须匹配 release_manifest）、`dpu_fingerprint`。
这是加载端真实核验后的记录，禁止为了绕过检查手工伪造成功记录。
通过后才会写出驱动所需的 `DPU_POINTS_BOARD_PREFLIGHT_PASS`。

```bash
python -m orb60.kv260.point_pl.board_smoke --uio /dev/uioN \
  --abi point_abi.json --release release_manifest.json \
  --deployment-receipt deployment_receipt.json --output point_board_preflight.json
```

`uioN` 必须按实际节点查找。确认新硬件就绪后，在 `dense_service.py` 显式选择 `PlFusion`，
将对应 Projector 传入并在退出时关闭。当前生产入口未自动改为新硬件，也没有增加 CPU 回退。
