# Zynq-7015 固定地图定位交接包

本包给接手者开发“摄像头 → FPGA ORB → PS 固定地图定位 → HDMI 显示”使用。提供同一次建图的原始稀疏地图、真实 FPGA 黄金特征、冻结参考定位器及验证工具。**相机内参为借用的临时内参，坐标是单目相对尺度，轨迹不是外部测量真值。**

本包不包含彩色／稠密点云、深度模型、摄像头驱动或新的 HDMI 工程。当前 bitstream 只有 ORB 图像引擎与描述子核；摄像头、HDMI 集成和最终 Cortex-A9 定位应用由接手者实现。

## 先跑通离线数据

电脑需 Python 3.12 以及 `requirements.txt` 中的包；准备依赖后无需 FPGA、RK3588 或网络。推荐在解压根目录执行：

```text
python tools/verify.py --bundle . --output verification
```

该命令核验全部文件 SHA256、2,273 帧真实硬件回复及历史 CRC、视频灰度像素、地图描述子关联、重投影和 20 组固定内点位姿。输出 `verification/verification.json` 和几张无 GUI 的显示示例。`PASS` 表示包内数据与参考测试通过；没有提供候选程序输出时，不代表新 PS 应用已经通过。`--skip-video` 仅用于快速检查，不代表视频像素验证通过。

本机冻结版本：Python 3.12.12、OpenCV 5.0.0.93、NumPy 2.5.2、PyAV 18.1.0、Matplotlib 3.11.2。独立 C++ 验证使用 OpenCV 4.2.0。跨版本完整 RANSAC 可能选择不同内点，必须用误差报告判断，不能简单把函数返回成功当作验收。

## 内容导航

| 目录／文件 | 用途 |
|---|---|
| `map/points.bin`、`point_ids.bin` | 2,547 个可靠原始世界点；小端 float32 XYZ 和 uint64 ID |
| `map/sparse_raw.ply` | 无 RGB、无缩放的原始稀疏 PLY |
| `map/representative_descriptors.bin` | 每点一个实际观测描述子，按 points.bin 的顺序排列 |
| `map/observations.csv`、`observation_descriptors.bin` | 18,980 条观测与描述子，一行对应 32 字节 |
| `map/keyframes.csv` | 130 个关键帧，原始 Twc、相机内参和时间戳 |
| `map/slam_reference.csv` | 原 SLAM 的 2,273 行规范轨迹，包含跟踪状态和有效性 |
| `golden/` | 全部 2,273 帧、1,923,654 条重新采集的物理 FPGA 特征及原始回复证据 |
| `localization_reference/` | 固定地图参考定位器的完整输出、配置和固定内点算例 |
| `source_map/` | 同一次建图的未修改原始导出／日志；不是重新运行 SLAM 得到的地图 |
| `testdata/` | 完整原始 MP4 与工作帧清单 |
| `reference/` | PS 引擎、写合并驱动、跨帧调度、无 Qt/OpenGL 的投影／绘制辅助代码 |
| `fpga_baseline/` | 配对 HLS 源码、生成器、测试向量、IP、routed DCP、bitstream、寄存器和完整路由报告 |
| `reports/` | 数据验收、独立 C++ 解算对照、原 SLAM 一致性图表和测试结果 |
| `tools/` | 离线验证、解码、定位、比较和 AMD 构建入口 |

`preparation.json` 是材料冻结阶段的历史记录；最终是否可交付看 `delivery.json` 和 `reports/package_acceptance.json`。原始文件中的历史绝对路径只作来源记录，不作为复现依赖。

## 输入与时间戳

原视频 SHA256：`c2ab71867980667111e365ea49ddbc618baa8400b3a5723d10652b204f76a7f4`。该视频已有 960×720 工作尺寸，无需再缩放、填边或旋转。原视频含 2,297 帧；原建图忽略了前 24 帧，因此工作帧 0 对应源帧 24，工作帧 2,272 对应源帧 2,296。

必须用 PyAV `frame.to_ndarray(format='gray')` 解码灰度，不能用 BGR 转灰度近似代替。不能按 30 FPS 重算时间戳：清单中的 `timestamp_ns` 是冻结的整数纳秒身份，`mp4_pts_s` 是视频显示时间，两者分别保留。禁止将整数纳秒先转 float32；CSV 的时间戳按十进制整数解析。

生成供 PS 回放的紧密 GRAY8 数据：

```text
python tools/export_inputs.py --bundle . --output gray_replay
```

输出 `gray8.bin` 和逐帧偏移清单，每帧 691,200 字节；全段约 1.57 GB。仅验证一帧可加 `--frame 200`。解码时再次核验逐帧像素 SHA256。原视频及原清单只读。

## 特征格式与精确比较

`golden/features.bin` 连接所有帧的原始记录。`golden/frames.csv` 的 `record_offset` 单位是**记录**，不是字节；`count` 给出当前帧数量。记录固定 64 字节、小端：

| 字节偏移 | 内容 |
|---:|---|
| 0、4、8 | uint32 x、y、FAST score |
| 12、16 | uint32 金字塔 level、A32 方向 bin |
| 20、24 | int32 m10、m01 |
| 28 | uint32 angle，单位为度的 Q16，等于 bin×737280 |
| 32…63 | 32 字节 BRIEF，位顺序原样保留 |

x/y 是**对应层的整数坐标**。回到第 0 层时，用 float32 从 1.0 开始反复乘 float32(1.2)，再以 float32 乘 x/y；参考 `common.feature_points()`。不能把 double 的 `pow(1.2, level)` 当作字节兼容实现。CPU OpenCV ORB 的选点／方向／描述子不能替代这些特征。

`runtime.bin` 每帧 1,152 字节：128 字节原元数据＋8 层×128 字节统计；`headers.bin` 每帧 64 字节原始网络回复头。验证器会重组回复，核验帧号、时间戳、后端标志、ABI、计数、CRC 和周期字段，并与历史建图日志逐帧对照。整段采集只有物理 FPGA 请求，CPU ORB 调用为零。

接手程序把实际特征输出为同样的 `features.bin` 和 `frames.csv` 后运行：

```text
python tools/verify.py --bundle . --output acceptance_features --candidate-features YOUR_FEATURE_DIRECTORY
```

每帧的数量、顺序和全部 64 字节必须一致。不同图像解码、阈值、边界策略或排序会直接失败。

## 地图与坐标约定

保留原始 map_0 的世界原点、轴向和相对尺度，未进行中心化、归一化、Sim3 拟合或重新建图。Twc 为行主序 4×4，相机坐标 → 世界坐标；相机约定 x 向右、y 向下、z 向前。对世界点 Pw，`Pc = Rwc.T @ (Pw - twc)`；PnP 返回 Rcw、tcw，需要转换 `Rwc=Rcw.T, twc=-Rwc@tcw`。

`points.csv` 与二进制顺序相同，给出 point_id、原始 XYZ、代表观测行号。代表描述子是在该点实际观测中，选择与其他观测 Hamming 距离中位数最小者；同分取第一行。`observations.csv` 保留原导出的所有字段，并新增 frame_index、record_index、descriptor_row。raw_u/raw_v 是畸变图上的实际特征坐标，u/v 是去畸变坐标；匹配后先去畸变，再用无畸变 PnP，不能重复校正。

参考深度 `map.json.reference_median_depth` 为首个关键帧可靠观测的正相机 Z 中位数，约 **1.0068744421**。它只用于无量纲误差阈值，地图本身没有除以这个值。2,547 是保留的可靠点数，原日志里的全地图点数可能更大。

临时内参 fx≈910.072、fy≈914.094、cx≈485.523、cy≈336.718，畸变见各关键帧及 map.json；它们是历史录像使用的借用内参，不适用于新摄像头。接手新镜头须提供实际标定，并保持尺寸变换与内参同步。

## 轨迹证据与验收

有两个不同的参考，必须区分：

1. `map/slam_reference.csv`：原 FPGA＋RK3588 SLAM 的轨迹，2,081 帧有效；用于整体一致性诊断。
2. `localization_reference/trajectory.csv`：本包独立固定地图 Hamming＋PnP 定位器的冻结结果，2,273 行、1,803 帧有效；用于后续固定地图定位回归。

原日志 `Diagnostics_map0.txt` 的首列虽然像 TUM 格式，实际单位为纳秒。末尾时间戳 74075225400 重复 82 行，位姿完全相同；原 TrackingStates 显示丢失跟踪。规范清单以实际源帧和状态为准，所有失效行 Twc 留空，不重复最后位姿、不插值。

冻结定位器配置见 `configuration.json`：每帧独立 Hamming 2-NN／ratio 过滤，一点一匹配，去畸变，固定种子的 EPNP RANSAC，再对固定内点 ITERATIVE 精化。只读取地图，不更新地图，不运行 SLAM。完整重算：

```text
python tools/localize.py --map map --golden golden --output MY_LOCALIZATION
python tools/verify.py --bundle . --output acceptance_pose --candidate MY_LOCALIZATION/trajectory.csv
```

候选 CSV 使用同样字段和原帧号、map_id、整数时间戳、pose_valid、行主序 twc_00…twc_33。失败帧保留一行并标为无效。比较不做轨迹对齐或尺度修正。

| 门禁 | 阈值与结果范围 |
|---|---|
| 同对应点、同内点的解算 | 平移≤参考深度 0.1%，旋转≤0.1°；包内 20 组 Python／独立 C++ OpenCV 4.2 已通过 |
| 新定位器 vs 冻结固定地图参考 | 位置 P95≤参考深度 2%，旋转 P95≤2°，覆盖参考有效帧≥95%；接手者程序须另测 |
| 固定地图参考 vs 原 SLAM | 仅诊断：共同有效 1,798 帧，覆盖 86.40%，位置 P95约0.556%，旋转 P95约0.565°；没有宣称达到95%原SLAM覆盖率 |

独立 C++ 固定内点实测最大位置误差约参考深度 **0.00136%**、旋转 **0.00195°**。它证明读取、位姿方向和固定解算在两个实现／版本间一致，**不是 Zynq PS 定位程序的验收**。未来代码覆盖率分母必须取冻结参考的全部有效帧，不能只选成功帧。

`reports/slam_consistency/` 有逐帧误差 CSV、轨迹叠加和误差曲线；该目录状态为 DIAGNOSTIC_ONLY。不能将它或历史 SLAM 日志中的 PASS 混成新 PS 应用已通过。

编译独立 C++ 算例（已有 OpenCV 开发环境的 Linux）：

```sh
g++ -O2 -std=c++17 reference/fixed_pnp.cpp $(pkg-config --cflags --libs opencv4) -o fixed-pnp
python tools/check_cpp.py --bundle . --program ./fixed-pnp --output cpp_pnp.json
```

`pnp_cases` 保存固定的三维点、已去畸变二维点、实际 RANSAC 内点及初值。PS 可直接使用这些输入，对照解算层阈值，避免把不同匹配结果误归因于浮点误差。

## PS 调用与显示参考

`reference/ps/engine.c` 是实际用过的直接 AXI MM 调度。图像核 0x43c00000、描述子核 0x43c10000；以生成的寄存器头为准，不手填旧核偏移。专用 DDR 从 0x20000000 开始，16 MiB；Linux 设备树必须提供匹配的 no-map 保留区。原图三槽、blur 两槽及特征／统计区域由 engine.c 定义。第 n 层描述子与 n+1 层图像处理重叠；输入帧的网络接收槽独立，不能提前覆盖仍归 PL 使用的槽。

`reference/ps_direct_example.c` 演示直接调用并保存完整 64 字节特征记录；`reference/ps/pipeline.c` 演示有限队列、帧号以及接收／PL／发送的所有权。调用 UIO 只能有一个拥有者，不能让网络服务和新的定位应用同时访问。所有 ap_start 后错误都停止并要求重置／重载 PL，不能在未知硬件状态下直接跑下一帧，也没有 CPU ORB 回退。

`reference/ps_writecombine/orb60_wc_uio.c` 将专用保留 DDR 以写合并方式映射，控制寄存器仍为 Device 属性。保留发布屏障、完成状态和最终写响应／PS 可见性检查，禁止同时存在缓存别名。留存 .ko 只适配记录中的 4.14.0-xilinx #52 配置与符号版本；新内核须按对应源码重编译。文档中的实验性恢复脚本保留原意，不是新板通用安装器。

`reference/reference.c/.h` 提供小端地图读取、Hamming256、世界点投影、GRAY8→RGB565、特征叠加和轨迹线绘制，不依赖 Qt/OpenGL。`tools/render.py` 是电脑软件投影示例；`verification/previews` 可作为颜色／轴向和绘制布局参考。接手者可把输出像素送到自建 framebuffer／VDMA／HDMI 链路。它们没有实现摄像头采集、视频时钟或 HDMI 时序。

## PL 基线与重建

器件 xc7z015clg485-2，4PPC、150 MHz、960×720、8 层，预算 1000；bitstream SHA256：`b7fc66eef0895469506e04f7b8e26f0ef6232bc3f055db5bce9609a153d42c60`。

| 完整路由指标 | 留存值 |
|---|---:|
| Setup WNS / TNS | +0.093 ns / 0 |
| Hold WHS / THS | +0.036 ns / 0 |
| Slice | 11,452 / 11,550，99.15% |
| LUT | 34,990 / 46,200，75.74% |
| FF | 37,001 / 92,400，40.04% |
| BRAM tile | 70.5 / 95，74.21% |

报告是已验收同一 ORB 顶层的历史完整路由，不是新 HDMI 顶层的预算。**Slice 几乎用满，增加摄像头／显示链路必须重新评估布局和时序。** 旧视频设备树中的设备和本 ORB 地址存在复用；现有运行脚本会停用原视频／音频设备。不能把本 ORB bitstream、旧 HDMI 设备树和地址定义直接混用。

架构选择：保留自定义 HLS ORB；PS 负责匹配、PnP 与软件渲染；DDR／仲裁／时钟／复位保留 AMD IP。目标 HDMI 扫描输出采用成熟视频 IP或接手者已有设计，在新顶层独立验证。本次没有增加 PL 核，也没有重新布局布线。

独立包使用 `scripts/project_env.ps1`，通过环境变量 `FPGA_VIVADO_ROOT`、`FPGA_VITIS_HLS_ROOT` 指向本机 AMD 2024.2，或在不分发的 `scripts/local_env.ps1` 设置。使用短且无空格的新输出目录：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_hardware.ps1 -BundleRoot . -Output D:\orb_build\layer -Stage HlsLayer
powershell -ExecutionPolicy Bypass -File tools/build_hardware.ps1 -BundleRoot . -Output D:\orb_build\descriptor -Stage HlsDescriptor
powershell -ExecutionPolicy Bypass -File tools/build_hardware.ps1 -BundleRoot . -Output D:\orb_build\top -Stage Top
```

Top 默认采用包内已配对的两个 IP；若修改 HLS，必须把通过验证的新 IP成对集成，并重新跑 golden／C sim／综合／co-sim／AXI协议／完整顶层路由。HLS 参数取两个独立冻结快照，不能只用一份最新实验源替代。`-Stage Top -ValidateOnly` 只校验 BD，不生成 bit。重建结果不保证二进制哈希相同，须以新功能与路由证据验收。构建脚本会拒绝覆盖已有目录。

## 接手验收顺序

1. 先运行离线验证，打开原始稀疏 PLY、特征叠加样例和轨迹误差图，确认坐标／字节序。
2. 用冻结灰度输入验证新板 FPGA 输出，逐字节比较全部特征。
3. 用固定对应点／内点验证 PS 位姿解算，排查 Twc/Tcw、畸变、矩阵排列。
4. 用完整视频与同一地图验证 PS 匹配＋定位，输出逐帧 CSV 并运行比较命令。
5. 最后接真实摄像头和 HDMI。新相机先标定；真实时序、DDR／缓存、持续吞吐、摄像头和显示均需板上实测。

以上门槛不允许通过重新建图、自由尺度配准、重复最后位姿或 CPU ORB 来掩盖不一致。许可证与上游说明见 `LICENSES/`，原始录像与地图仅作本项目交接测试数据。
