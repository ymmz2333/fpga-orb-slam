# HDMI_2 整机实现工作记录

2026-10-23 用户明确选择板载 HDMI_2，并要求本次落实摄像头以外全部功能；显示器已连接并通电。继续完成 RTL、仿真、2018.3 综合布线、软件、SSH 上板与 SD 启动部署。保留原 SD 文件与可恢复备份，不使用 JTAG、不写 flash。摄像头保留接口，测试输入使用原录像。

已确认 ACZ7015 / xc7z015clg485-2，SSH root@192.168.1.233:22，现有主机密钥验证成功。板上 ARMv7 Linux 4.14.0-xilinx #52、glibc 2.26、SD p2 rootfs、p1 FAT 启动分区。默认 PL 有 fb0 800×480，没有 UIO/V4L2；默认视频与新 ORB 地址冲突。旧 load_board.sh 会关闭旧视频，不能直接用于新 UI。手册 PDF 第 26 页 HDMI_2 引脚：时钟 T2/T1，数据通道 2 K7/L7、1 M8/M7、0 N6/N5。

已实现轻量独立 RGB565 DDR 扫描核心，共享 mem3 的 HP3；ORB 保持原 4PPC/150MHz、寄存器地址与 DDR ABI。为复用配对 WC 驱动，最终视频控制地址是 **0x43c08000**，与 layer 共用原 UIO map0 的 64KiB 映射；硬件解码分别为两个32KiB区段。1280×720p60，74.25MHz 像素，371.25MHz 串行时钟；HDMI_2 输出 TMDS 视频（DVI 视频模式，无音频）。两个缓冲槽分别为 **0x20b00000 / 0x20d00000**，槽跨度和预留大小为2MiB，位于原16MiB映射中RX槽之后的空闲区；逐个核对原引擎的raw/blur/point/stats/features/RX访问边界，显示不覆盖任何原工作区。单一进程、单一UIO打开和单一WC DDR映射共享两个功能，避免额外内核驱动和缓存别名。当前DT已reserve/no-map 0x20000000起512MiB。

周期合同：AXI 150MHz 只读，64bit、最多64拍、一笔 outstanding；AR/R 遵守反压，边界不跨4KiB。像素与 AXI 之间采用2018.3原生 XPM async FIFO。每次垂直消隐请求新帧，AXI 先排空已承诺事务再清 FIFO 和选择新缓冲；不能撤销已拉高但未握手的 ARVALID。发生欠载时该帧剩余像素黑屏，记录计数，下一个垂直消隐恢复；不能把后半帧错接到下一帧。PS 仅可提交两个合法缓冲，等待切换确认后才能重用原缓冲。未配置 DDR 时上电显示片上测试图，便于独立检查 TMDS/时钟。

当前 ORB 已布线 Slice 99.11%，视频合入后必须重新实现；不能沿用旧时序验收。软件优化版 ARM 构建 build/arm_20261023_172351 已通过编译/本机测试，并在板上通过全部 CPU 自测。240帧真实特征回放从33.505提升至37.467 FPS、134帧有效、880点、16关键帧、峰值RSS8.36MiB；22帧超过33.3ms且不包含提取/显示，整机30FPS仍未通过。

已生成的 ORB-only bit/HDF 位于 ../.work/z18/20261023_133841/bit_20261023_165856；尚未将该 bit 加载板卡。板上暂存软件包 /tmp/sd_ssh_20261023_172535，真实特征输入 /tmp/arm_replay_20261023_171944；优化版板端证据已取回 output/zslam-evidence-20261023_172535.tar.gz，SHA256 02b6d9116521c7d4c8d0e362745a4b73f826234e99a4f4c87b7c7dabbfec554d。

18:58进行中：HDMI完整候选综合 ../.work/z18/20261023_181526，45项配置与642个冻结IP哈希PASS；setup综合估计+0.114ns。该候选已布线，route_20261023_182409报告：WNS -0.024ns（1端点），WHS+0.036ns，66,063网全路由、0错误，Slice11,516/11,550(99.71%)，LUT36,714、FF38,435、BRAM73.5、DSP44。4个TMDS正端口没有常规输出delay模型（串行接口外部边界），内部端点覆盖完整；未伪造外部接收器/PCB时序值。opt_20261023_185015正从保留DCP执行critical_pin_opt、routing_opt及Explore重布线，尚未通过最终setup验收，不生成/加载失败bit。

RTL仿真PASS：build/video_sim_20261023_174721（TMDS穷举解码/控制/DC）；build/video_sim_20261023_174754_600587_tb_video；build/video_sim_20261023_180409_189028_tb_video_full（90,112像素、370突发、长突发/FIFO满载/欠载恢复）；../.work/vs18/1023_183523_936243_serializer（UNISIM真实OSERDESE2主从10:1逐位、5xDDR、差分608位）。早期serializer TB虚构初始clock边沿导致假失败，已修复采样对齐并通过；一次2018.3长路径Tcl_Close崩溃保留在build/video_sim_20261023_183024_751115_tb_serializer，短路径重跑通过。

PS程序已加入--hdmi-uio共享映射、双缓冲提交/确认/欠载与AXI错误报告、--verify-golden逐字节核对真实PL输出。重定位增加有广泛几何支持的运动先验快路径，失败仍回退原完整搜索；新CPU性能尚待板测。最近ARM构建build/arm_20261023_184221通过，之后增加wc1 provider检查，需再次构建。scripts/check.py本机回归已PASS，最后ports.cpp还需重跑。

SD原文件备份：output/zslam-sd-original-20261023.tar.gz，SHA256 696f525d92eac48b21a26fb8235bfc864bdf46301abb68f22a2f9d566b932fd5；已解包到output/sd_original_20261023。主机libfdt工具tools/prepare_device_tree.c由SDK2018.3原始BSD库构建，输出output/dt_hdmi_20261023/system.dtb及orb60-hdmi.dtbo；scripts/check_device_tree.py独立解析核对89节点，仅12个预定status改变与新增共享UIO。尚未应用overlay或修改SD启动文件。

原录像用冻结tools/export_inputs.py和PyAV18.1逐帧校验后导出全部2273帧，../.work/video_inputs_20261023/gray8.bin=1,571,097,600字节。归档../.work/video_inputs_20261023.tar.gz=854,953,114字节，SHA256 8dcaeec0a513b6938027b300c93b97e0c941474d40f40cdb0f5b057fb4d13f31；已上传/opt/zynq-slam/data/video_inputs_20261023.tar.gz.part并通过归档哈希，板端正在解压/逐文件校验。主机原视频testdata/video.mp4原生960x720/30Hz，帧24起对应golden第0帧；OpenCV BGR2GRAY解码哈希不同，必须使用已校验PyAV导出。

SD uEnv.txt使用system.bit、system.dtb、zImage，root=/dev/mmcblk0p2；原uenvcmd=saveenv，部署时避免新增flash保存指令，后续检查该字段。rootfs可用约4.6GiB，/tmp总254MiB，完整录像必须放/opt而不能放/tmp。板上无dtc/modinfo命令。配套WC模块在冻结reference/ps_writecombine/retained_build/orb60_wc_uio.ko，源码与当前#52内核匹配，原驱动未修改；用户态共用16MiB，故无需新模块ABI。烧板前必须运行已读源码的reference/ps/retained_build/board-probe，确认7015 ID/100MHz FCLK及四HP64bit；旧视频/音频/DDR alias驱动须按消费者先卸载，再全PL重载、应用overlay并显式绑定WC。保存旧bit的Bootgen转换作为易恢复的RAM加载后备，先跑实时再部署SD。用户已授权本次落实全部非摄像头功能，显示器接好；无需重复询问泛化许可。

工作仍在进行。验收必须覆盖 TMDS 编解码和消隐、AXI/FIFO 欠载恢复、综合/布线与全部时钟约束、PL 输出一致性、UI 切换和 HDMI 实物画面、整机帧时和内存，以及保留恢复路径的 SD 开机运行。

20:30后进展（此前日志是历史记录）：切模式仅在vblank生效的最终RTL通过新仿真 ../.work/vs18/1023_193605_711430_video_full（90112像素/371突发），综合 ../.work/z18/20261023_194328。增量布线 route_20261023_195215 全部11项验收PASS：WNS+0.015/WHS+0.013ns、66068/66068网0错、Slice11523/11550(99.77%)、LUT36777/FF38422/BRAM73.5/DSP44；内部覆盖完整，4个TMDS外部序列化边界单列；CDC无Warning/Critical，Gray skew通过。bit/HDF final_20261023_201146 已校验打包并通过SSH RAM加载，WC驱动绑定/dev/uio0；原SD文件未改。用户明确反馈“点云有画面”。

首轮真实链路360帧：每帧原始灰度->PL->golden逐字节核对->SLAM->HDMI，8.75994FPS，223有效，1138点/16KF，RSS9.145MiB；扫描60.0112Hz，0欠载/0AXI错误。证据output/zslam-physical-evidence-202900.tar.gz SHA256 fbf6fd4ce621d1dcd9c0035a162108ddde4f3bfd7340cdcea3139cd7a61c9b3d。阶段平均capture24.377、ORB9.479、SLAM18.302、render58.238、present3.503ms。UI消除逐像素函数/边界检查后第二轮360帧提升14.2255FPS，225有效、1193点、扫描60.0122Hz无错误。尚未满足30FPS。

先验恢复快路径发生16.46vs37.43FPS性能回退，已撤回。完整2273帧旧恢复仅186有效/5.09FPS，P3P替换后525有效/5.46FPS，说明短片段不足以验收；随后加入紧密描述子缓存与NEON无栈回写归约，并正在分拆采集/ORB/SLAM绘图为有界流水线及逐阶段计时。新建图不是原ORB-SLAM3，长序列质量仍需改进，不隐去LOST。

23:55前阶段记录：采集/PL ORB/SLAM与绘图已通过容量各2的有界FIFO流水线连接，保留完整输入顺序、取消/异常/EOF处理。SDK2018.3 GCC7.3.1 Cortex-A9/NEON构建、板上CPU自测均通过。P3P采用OpenCV4.2 BSD数值子集（无OpenCV运行时）；描述子使用NEON Hamming与近似多表候选检索，最终匹配仍做完整距离、比值及几何检验。原导入2547点固定为锚点，新点独立优化；地图v2保存fixed标志并兼容读v1。UI灰度采样的全部371712像素核对通过；右向基向量已修复，移动视锥正向测试通过。绿色图像特征为每帧独立ORB角点，不代表持久跟踪ID。

完整2273帧物理链路中，固定锚点+新增建图+静态UI优化得到28.82155FPS、2057有效、3000点/16KF、RSS12.73047MiB；0丢帧、全部ORB记录逐字节相同、HDMI约60Hz且0欠载/0AXI错误。连续三次全局重定位失败后按3帧间隔尝试得到29.79343FPS/2051有效；5帧间隔得到30.21788FPS/2050有效、RSS12.54688MiB、314次33.3ms超限，300帧分段最低29.25893FPS，尚不足以称为持续各段30FPS。正常跟踪逐帧执行，跳过全局尝试的帧保持LOST无效，不复用成功位姿。5帧间隔共同有效2047/原参考2081，原坐标无对齐位置P95=0.0056165单目世界单位，旋转P95=0.520106度；这是同录像参考诊断，不是独立真值精度。

上述原始日志与地图/截图归档output/zslam-bench-235200.tar.gz，SHA256 fce71dc5b04d6b7f12d152d512203b743a0616f2ca47bf3f7815c77398bc3fb0，已取回并核对。新增点云投影缓存精确比较全部点坐标、ID及颜色阈值，仅复用未改变的点云投影，视锥与轨迹仍逐帧更新；缓存/移动视锥/重置清图与全量重绘逐像素一致测试通过。build/arm_20261023_235120及包sd_ssh_20261023_235333正在上板测试默认3帧恢复间隔。SD脚本、原文件备份、启动目录和各SysV运行级已检查，实际SD安装/重启待本轮测试后执行。
