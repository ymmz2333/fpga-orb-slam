# KV260 单板系统：第一阶段稠密链

本目录是 KV260 迁移的统一源码入口。最终目标是一块 KV260：PL 上的 ORB 提取特征、DPU 估计深度，PS 运行 SLAM、地图管理和点云融合。本阶段只完成稠密模块与电脑验证；现有 Zynq7015、RK3588 生产入口及其验收限制保持原样。

**最新模型选择：采用用户已认可视觉效果的 MiDaS Small 端到端 QAT 微调版。** 选择记录见 `../../kv260/config/depth_model_selection.json`。该权重对应的 B4096 组件 xmodel 现已编译，结果位于 `orb60/build/kv260_system/depth_midas_qat/compiled/`：99 个卷积均在 7 个 DPU 子图中，PS 的 4 个额外 ReLU 采用模型绑定策略逐项核对。用户视觉接受与原数值门槛分别记录：原 3%/0.98 门槛仍未通过，DPU 板端测试尚未进行。

单板 ORB、PS 建图与 RGB 点云编排入口为 `orb60/kv260/run_system.py`，GPU 显示默认采用独立点云窗口。完整硬件平台、实际 DPU 输出和 Mali/HDMI 仍待上板核对。

此前 FastDepth 的 B4096 诊断编译及精度失败记录保留：38 个卷积均在同一个 DPU 子图中，CPU 只保留数据/量化边界。该 xmodel 属于旧候选，不能作为当前微调 MiDaS 的部署模型。

FastDepth 的源码适配在 `fastdepth/`，实际结果在 `orb60/build/kv260/fastdepth/`。电脑浮点回放为 97,623 点，INT8 量化参考回放为 104,244 点，均为真实 RGB 赋色。后者仍有缺口、重影及深度误差，不能以点数增加推断精度提高。完整对照见 `VALIDATION.md`。

## 如何理解这条链

1. 读取以前保存的关键帧 RGB、相机内参、稀疏地图观测和相机位姿。不重新运行建图，也不连接任何板卡。
2. 深度网络从 RGB 估计几何信息。MiDaS 原生输出相对逆深度；FastDepth 原生输出深度，PS 将它转换为统一的相对逆深度接口。单目 SLAM 场景中仍使用相对尺度。
3. PS 使用同一关键帧中的稀疏地图点估计逆深度的尺度与偏移。这里的几何拟合是重建算法的一部分；**量化精度验收不做此拟合**。
4. 把深度像素投回空间，用邻近相机视角筛掉不一致的点，并给点赋 RGB 颜色。
5. 保存每个关键帧的局部点云块，再进行有容量上限的体素融合，输出现有查看器可读取的二进制彩色 PLY。

深度网络推理与上述 PS 几何处理是不同工作。DPU 不承担本阶段的尺度拟合、赋色和融合。

## 文件位置

| 文件 | 用途 |
|---|---|
| `run.ps1` | Windows 统一入口，所有根路径从 `scripts/project_env.ps1` 获取 |
| `bootstrap_host.sh` | 建立独立 WSL Python 环境，不改变 RK 转换环境 |
| `run_host.sh` | 电脑浮点验证、真实关键帧回放、点云和测试 |
| `inspect_model.py`、`verify_float.py` | 静态形状折叠、上采样语义检查、原权重与 20 张参考输出核对 |
| `quantize.py`、`toolchain.sh` | Vitis AI 2.5 INT8 校准、逐张精度门槛与真实模型导出 |
| `compile_model.py`、`placement.py` | B4096 编译、指纹核对、DPU/PS 算子清单和 CPU 卷积拒绝检查 |
| `worker.py`、`tensors.py` | 三种显式后端及布局/量化边界封装 |
| `prepare_replay.py`、`replay.py` | 独立回放输入准备、几何筛选、彩色点云、位姿修正后重新融合 |
| `preflight.py`、`board_run.sh` | 上板只读预检、20 张硬件数值验收、回放比对 |
| `evaluate.py`、`preview.py` | 数值/点云差异和真实点云预览 |
| `package.py` | 带 SHA256 清单的交接包，不伪造缺失的目标模型 |
| `tests/` | 布局、边界、文件损坏、NaN、乱序、恢复、地图隔离和位姿更新测试 |

生成结果集中在工程根目录下的 `orb60/build/kv260/`：

- `float/float_gate.json`：20 张浮点验收。
- `model/model_inspection.json`：折叠前后结构及五个 Resize 的语义。
- `quantized/quantization_calib.json`、`quantization_test.json`：真实 Vitis AI 量化状态。
- `compiled/compilation.json`、`placement.json`、`arch.json`：真实编译状态与目标快照。
- `replay_inputs/`：可移植的 RGB、输入张量、观测、内参、整型纳秒时间戳、位姿及来源哈希。
- `reference_depth/`：电脑浮点逆深度及每帧身份记录。
- `cloud_reference/map_0/dense.ply`、`sparse.ply`、`blocks/`：实际点云和局部块。
- `pointcloud_preview.png`、`tests.xml`、`VALIDATION.md`：预览及验收说明。
- `kv260_dense_stage1_handoff.zip`：交接包；先读包内 `HANDOFF_STATUS.json`。

## 电脑运行

从工程根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File orb60/dense/kv260/run.ps1 -Stage Bootstrap
powershell -ExecutionPolicy Bypass -File orb60/dense/kv260/run.ps1 -Stage Host
```

统一入口默认 `-Family fastdepth`；需要重跑 MiDaS 对照时显式加 `-Family midas`。`-Stage Toolchain` 做校准和精度门槛，`-Stage CompileDiagnostic` 做明确标记的诊断编译，`-Stage QuantizedReplay` 做电脑 INT8 参考回放，`-Stage Package` 生成交接包。模型精度失败时 Toolchain 会非零退出，诊断阶段不会将其改成通过。

默认使用 WSL `Ubuntu-20.04` 作为电脑工具环境，**这不是目标板操作系统**。目标板仍为 Ubuntu 22.04 Kria。工具环境默认位于 Linux 用户目录的 `.local/share/orb60/kv260-host`，可用 `KV260_HOST_TOOLS` 覆盖。原有 RK 转换虚拟环境不会被修改。

主回放的数据来源是 `orb60/build/dense/room_full` 的保存位姿及观测、`room_full_detail` 的完整历史 RGB，以及原始 `recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4`。脚本核对视频和 RGB 文件哈希。历史 RK 输入张量哈希如果不能复现，会明确记录为 `historical_tensor_reproduction: NOT_REPRODUCED`；本次浮点与量化回放应共享新冻结的输入，不能把历史结果称为逐字节复现。

视频回归另用 `prepare_codec.sh`：只下载并解包 Linux 编解码依赖到独立目录，不安装系统软件包。测试本身使用明确标注的 12 帧合成视频，性能和点云实验使用真实录像及关键帧。

## 三种后端

统一四个位置参数：`MODEL INPUT_DIR NAMES OUTPUT_DIR`。`NAMES` 为文本清单，或 `-` 表示逐行标准输入。单个帧以 `ID.input.f32` 输入，生成 `ID.output.f32`；持久进程每完成一帧输出 `DEPTH_FRAME ID backend=...`。

```bash
python -m orb60.dense.kv260.worker MODEL INPUT_DIR NAMES OUTPUT_DIR --backend reference
python -m orb60.dense.kv260.worker quantized_reference.json INPUT_DIR NAMES OUTPUT_DIR --backend quantized-reference
python -m orb60.dense.kv260.worker MODEL.xmodel INPUT_DIR NAMES OUTPUT_DIR --backend dpu --preflight preflight.json --placement placement.json
```

- `reference`：电脑 ONNX Runtime 浮点参考，不能称为 FPGA/DPU 仿真。
- `quantized-reference`：Vitis AI PyTorch 的真实 INT8 量化参考，需要在对应容器环境执行。JSON 说明文件绑定原权重和校准配置哈希；也可使用真实导出的 TorchScript。
- `dpu`：仅在 aarch64 设备执行 VART GraphRunner。重新查询当前 DPU 指纹，验证编译图，失败立即退出，**不自动回退 CPU**。

外部输入固定 `[1,3,256,256]`、little-endian float32、RGB、ImageNet 均值 `[.485,.456,.406]` 与标准差 `[.229,.224,.225]`；输出固定 `[256,256]` float32 相对逆深度。内部 NHWC、int8 的边界转换封装于 worker。

FastDepth worker 增加 `--family fastdepth`。PS 在边界上还原 RGB `[0,1]` 并缩放到网络原生 224×224；网络本身保持五处 nearest/asymmetric 上采样。PS 将原生深度缩放到 256×256，再取逆深度，非正/无效区域标记为 0，并在几何拟合中排除。上述操作不是 DPU 卷积推理，也不是用几何对齐掩盖量化误差。

FastDepth 权重来自 [Axelera 发布的 FastDepth 模型说明](https://github.com/axelera-ai-hub/voyager-sdk/blob/latest/ax_models/zoo/torch/fastdepth-nyudepthv2-onnx.yaml)，上游为 [MIT FastDepth](https://github.com/dwofk/fast-depth)。下载 MD5 与发布说明一致，同时固定 SHA256。其 ONNX 使用普通卷积、ReLU6、加法和近邻上采样；适配器读取真实权重构建 PyTorch 图，20 张样本与原 ONNX Runtime 逐张验证，不生成替代权重。

先运行已有回放输入准备，再使用 `fastdepth/run_host.sh`。在固定 Vitis AI 容器内，`fastdepth/toolchain.sh` 执行实际校准与数值检查，`fastdepth/compile.sh` 显式进行诊断编译，`fastdepth/quantized_replay.sh` 生成 INT8 参考点云。失败状态保持失败，原 3% / 0.98 门槛未修改。

上板包的 `diagnostic_models/fastdepth/` 是未通过精度验收的真实编译产物。未来由操作者准备匹配平台后，可显式运行 `fastdepth/board_diagnostic.sh` 获取真实 DPU 的 20 张结果；脚本会在数值验收失败时停止。它不会把诊断模型提升为可部署模型。

每帧记录输入、模型、输出哈希和实际后端。恢复时先核对已有输出；损坏文件、NaN、尺寸不符、重复/乱序或清单未完成都会失败。输出目录有进程锁，不能同时用两个 worker 写入。失败输出不会被标为 DPU 成功。

## DPU 工具链和算子语义

组件验证目标为官方 **KV260 单 B4096 / Vitis AI 2.5**。镜像固定为：

```text
xilinx/vitis-ai-cpu@sha256:eaa85efb06924995ebdb973546e7f69169b003b8cc525764bd9524ad554dddbe
```

官方 DPU-PYNQ 文档指出 KV260、ZCU102、ZCU104 的此版本使用相同 DPUCZDX8G_ISA1_B4096 架构，因此首版使用镜像中 `/opt/vitis_ai/compiler/arch/DPUCZDX8G/ZCU104/arch.json`。编译必须保存该文件和哈希；实际板上以查询到的指纹为准，不能仅凭 Ubuntu 版本判定兼容。

四处 refinement bilinear Resize 保持 `align_corners=True`，最后一处保持 `half_pixel`。不能改成 nearest 或另一种坐标规则来通过编译。PS 允许清单仅包括明确的 Resize、张量形状/布局转换、量化边界、常量和数据搬运；不允许卷积静默落到 CPU。`placement.json` 必须有实际 DPU 子图和卷积，列出 PS 运算，并验证 Resize 属性；不能解析的属性视为未通过。

VART GraphRunner 负责整张异构图的调度，DPU 子图使用 VART，受支持的 CPU 辅助节点由官方 CPU runner 执行。独立 NumPy bilinear 实现与 PyTorch 的 align_corners/half_pixel 测试用于核对语义，不替代未通过的硬件验收。目标板若缺少 GraphRunner 或对应 CPU runner，应明确失败。

`run_toolchain.sh` 连接显式指定的 Docker socket，不创建系统服务；支持 `KV260_DOCKER`、`KV260_DOCKER_HOST`。使用前需准备可用 Docker 及固定镜像。执行时网络关闭，只挂载工程。环境/编译日志保存在结果目录。需要自行满足 AMD 工具及模型许可证条件。

没有现成 Docker 时，可以在 WSL 用 `bootstrap_toolchain.sh` 准备本次实际使用的独立 Docker 二进制（校验下载哈希），在单独终端前台运行 `start_toolchain_service.sh`，再在工作终端运行 `pull_toolchain.sh`。两者只使用专用目录和 socket；不安装系统服务。用完在服务终端 Ctrl+C 停止。

```powershell
powershell -ExecutionPolicy Bypass -File orb60/dense/kv260/run.ps1 -Stage Toolchain
```

量化验收恰好使用原 20 张真实样本，逐张要求 NRMSE ≤ 0.03、Spearman ≥ 0.98。NRMSE 分母是参考输出 P95−P05。没有事后 min/max、尺度或偏移拟合。任何一张失败，目标模型不得进入已验收的上板包。

当前实际尝试了 `native-static` 和 `reluk-cle` 两种校准方案，均固定 SAME padding 并保留原权重与插值语义。Vitis AI 2.5 默认的 ReLU6→ReLU 替换被禁止。转换浮点检查与真正的校准使用独立模型实例，且要求所有卷积参数都有完整 INT8 校准值。实际精度与通过数量见 `VALIDATION.md`；不能把导出成功或编译成功当作精度通过。

若精度失败，`run_diagnostic_compile.sh` 可以显式运行诊断编译。其产物只进入 `diagnostic_models/`，不会成为 `models/` 中的可部署模型。编译后检查记录真实 `dpu_fingerprint`；旧版官方 `arch.json` 只有目标名称时，以编译器输出的目标名称和指纹绑定该快照。编译器可能把最终 half_pixel 上采样降低成 DPU 卷积类算子；源图五处插值属性和编译图四处 PS 上采样都会记录，最终数值仍须板端验收。

## 局部块和位姿修正

每个地图单独保存 `map_N/blocks.json` 和 `blocks/*.npz`，含相机局部坐标 `xyz_camera`、RGB 和原始 `Twc`。`Twc` 将相机坐标变到 SLAM 世界坐标。PLY 导出再除以首个有效稀疏深度中位数，属于相对尺度。

位姿修正文件：

```json
{"map_id":0,"poses":{"m0_k90":[[1,0,0,0.1],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}}
```

```bash
python -m orb60.dense.kv260.replay update-poses --folder OUTPUT/map_0 --updates corrections.json
```

从局部块重建全局点云，避免反复变换已有融合结果引入误差；支持多次部分修正。不同地图不能互相套用位姿。大幅回环修正可能改变可见性，需重新运行多视角筛选，不把已有支持关系视为永远成立。

## 上板操作

交接包不升级系统、不加载 bitstream/xclbin、不修改 `/etc/vart.conf`、启动文件或固件。由操作者准备匹配平台后，在解压根目录运行：

```bash
# XRT_VERSION 来自所用板卡平台的构建/发布记录，不从电脑镜像版本猜测。
python3 -m orb60.dense.kv260.preflight --arch models/arch.json --output board_output/preflight.json --expected-xrt-prefix "$XRT_VERSION"
export KV260_EXPECTED_XRT_VERSION="$XRT_VERSION"
bash orb60/dense/kv260/board_run.sh
```

预检要求 Ubuntu 22.04、aarch64、VART/XIR/GraphRunner 2.5 配套组件、一致指纹及与明确平台记录匹配的 XRT 版本。当前尚未读取用户板上的平台记录，因此不预填 XRT 版本；缺失时明确退出。预检通过只表示配置匹配；还须真实执行 20 张 DPU 数值验收及完整点云回放。包内缺少已通过的 `.xmodel` 时，上板脚本会直接退出。

本阶段不宣称 KV260 实际 FPS、DPU 通过或整机实时。上板仍需核对 DDR、缓存一致性、驱动、视频输入、功耗和温度。下一阶段集成 ORB 时要生成 **ORB＋DPU 共存的统一硬件平台**，重新核对 `arch.json`、指纹、模型编译与共享 DDR；两个独立 bitstream 不能构成最终单板系统。

## 官方参考

- [DPU-PYNQ 组件和版本](https://github.com/Xilinx/DPU-PYNQ)
- [DPU-PYNQ 主机量化/编译说明](https://github.com/Xilinx/DPU-PYNQ/blob/master/host/README.md)
- [Kria-PYNQ Ubuntu 22.04](https://github.com/Xilinx/Kria-PYNQ)
- [Vitis AI 2.5 源码和文档](https://github.com/Xilinx/Vitis-AI/tree/v2.5)

源代码来源、原权重哈希、输入与结果哈希和实际工具版本以结果目录及上板包清单为准。
