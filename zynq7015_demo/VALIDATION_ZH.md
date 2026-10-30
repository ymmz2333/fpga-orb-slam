# 软件检查记录：2026-10-22

本轮仅编写程序，进行串行、少量数据的软件检查。没有运行 HLS、综合、布局布线、硬件加载或板测。原交接包没有改写。

实现为原生 C++17，PL 保留已有 ORB，新增建图、定位与 UI 在 Zynq PS 上运行。原 RK3588 完整工程不在现有包中，因此这里实现了新的轻量单目稀疏 SLAM，未声称与完整 ORB-SLAM3 等价。下述为2026-10-22软件阶段历史记录；2026-10-23起的ARM、物理HDMI、完整序列与SD验收更新见本文末尾及HDMI_IMPLEMENTATION_ZH.md。

本机编译：MinGW GCC 14.2.0，`-O0 -g0 -Wall -Wextra`，通过 fpga-python profile 启动，一次一个编译进程。仅关闭了紧凑语句的 misleading-indentation 风格告警，编译日志中没有其他告警。没有新增计算机全局 PATH 或依赖 WSL。源码及 Windows 检查程序不依赖 OpenCV/Eigen/Qt/OpenGL；生成单张预览时复用了先前独立临时环境的 PyAV/OpenCV。

| 检查 | 结果 |
| --- | --- |
| 四个原 ORB 引擎文件 SHA-256 | 与 `vendor/orb_engine/provenance.json` 一致 |
| ORB 记录读取 | 小端、严格长度、空帧、八层坐标、方向 ABI 和 float32 尺度检查通过 |
| 几何 | 已知合成场景的位姿优化、离群点拒绝、八点 RANSAC、双视图恢复、三角化重投影和静止场景拒绝通过 |
| 新建图与跟踪 | 合成场景从空地图初始化、连续变化位姿、有限关键帧和轨迹存储通过 |
| 丢失与重定位 | 空输入使位姿失效，恢复帧通过已存地图重定位 |
| 地图持久化 | 保存／加载定位、拒绝重复覆盖、CRC 损坏拒绝及失败加载保留当前地图通过 |
| 摄像头／显示接口 | 回调完整性、租约释放和不合规输入拒绝通过 |
| 原地图真实特征回放 | 第 200～207 帧 8/8 有效，使用 2,547 个点；按容量保留 64 个原关键帧 |
| 从零真实特征回放 | 检查原录像的前 240 帧；第 106 帧建立新地图，第 106～239 帧连续 134 帧有效；结束为 841 点、16 个关键帧 |
| 保存后的新地图再定位 | 加载上述新地图，在第 239 帧重定位有效，生成带对应原始灰度像素的 UI 预览 |

前 106 帧处于初始化，未输出伪造位姿。真实数据回放采用已有物理 FPGA 特征，不重新提取 CPU ORB，也不把原地图导入“从零建图”的运行。预览中的三维点来自这次新建地图；左侧图像源帧号和灰度 SHA-256 与原特征清单一致。

主要证据：

- `build/native/checks.json`、`unit_tests.log`：最终本机编译与单元检查。
- `build/native/real_data_smoke.json`：少量真实数据检查汇总。
- `output/accepted_fresh/trajectory.csv`、`timing.csv`、`run.json`：新建图回放。
- `output/accepted_fresh.zmap`：本次保存的新地图。
- `output/accepted_fixed/`：原地图定位回放。
- `output/ui_preview/dashboard.png`：真实图像＋新地图重定位的 UI 预览；界面明确标为 REPLAY。

测试中修正了初始化参考帧不及时切换、早期关键帧补充过慢，以及把必要的三角化挤出时间预算的问题。失败尝试及其日志保留在生成目录中；以此处列出的最终检查为准。局部 BA 使用有限预算，关键帧匹配和三角化维持独立的有界工作量。

尚未完成的硬件验收：Linux/ARM 目标 sysroot 编译，NEON 路径与物理 ORB 配对复验，摄像头和 HDMI 新顶层，缓存／DMA／复位、持续运行、同步显示、真实帧率和整机内存峰值。源代码中的 V4L2、UIO 和 framebuffer Linux 分支未在本 Windows 软件检查中运行。

30 FPS 是目标。PC 回放不包含 ORB 提取与物理扫描输出；检查过程中仍出现超过 33.33 ms 的帧，不能据此宣布整机 30 FPS 已达成。`run.json` 的 `hardware_acceptance` 明确为 NOT_VERIFIED。单张预览的 FPS 包含那一帧的重定位，不能代表稳定跟踪吞吐。Windows 无板端 RSS 数据，最终程序写 null；UI 的 CORE MEMORY 仅为核心已保留容量，不是整机内存峰值。

后续应先用匹配板端 Linux ABI 的工具链构建并检查 UIO/DDR，完成现有 ORB 的字节一致性测试，再接真实采集与同步显示驱动，最后执行持续整机 30 FPS 验收。新相机必须使用实测标定；本程序的单目地图为相对尺度。

2026-10-23硬件阶段已完成：Vivado2018.3完整HDMI_2顶层时序/路由/CDC检查与bit/HDF导出；SDK2018.3 ARM/NEON编译及板上全部CPU自测；配对WC驱动、共享DDR、UIO与HDMI_2物理显示。每轮2273帧原灰度输入经真实PL，黄金特征数量和全部64字节记录一致。对应独立run/display/timing/trajectory及同录像参考诊断记录在output/bench_235200/，归档SHA256见HDMI_IMPLEMENTATION_ZH.md。后续板测和SD重启结论按最终验收文件记录，不以早期软件结果代替。
