# KV260 DPU＋点云投影核

这是用户授权的独立硬件增量，不改当前主会话的无压缩输入和原融合入口。
工程位置 `D:/pld/orb60/kv260/point_pl/`。实现选择：规则逐点计算用自定义 HLS；
PS、DDR 接口、SmartConnect、时钟和复位用 AMD IP；地图管理、深度拟合、体素合并用 PS。

## 实际覆盖范围

```text
DPU 相对逆深度
  → PS：去畸变／缩放、稀疏观测拟合尺度与偏移、生成深度和掩码
  → PL：每隔2像素的采样点，反投影 → 相机局部XYZ → 世界XYZ，取RGB，过滤无效点
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

## 主会话使用

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
板端必须对真实关键帧比较点数、RGB、坐标误差、多视角筛选和最终点云差异，再测整链吞吐。
本次电脑验收不等于新点云核已完成板端执行。
