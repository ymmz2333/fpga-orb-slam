# 代码、器件与接口

器件 ACZ7015 / xc7z015clg485-2；顶层 s_wrapper。PS FCLK0=100MHz，ORB=150MHz；HDMI 像素 74.25MHz，串行 371.25MHz。当前目标是 PS+PL 协同，不是把全部 SLAM 放到 PL。

| 路径（相对 source/） | 责任 |
|---|---|
| src/main.cpp | CLI、实时有界流水线、控制键、日志、SLAM/显示线程衔接 |
| src/camera.cpp / include/zslam/camera.hpp | V4L2、MJPEG/GREY/YUYV、真实序号/时间戳、区域解码和标定采样 |
| src/ports.cpp | 原 ORB 引擎、单一 WC UIO 映射、HDMI 双缓冲和错误状态 |
| src/slam.cpp / include/zslam/slam.hpp | 两视图初始化、匹配、跟踪/重定位、关键帧和有界稀疏地图 |
| src/math.cpp / src/pnp.cpp | Essential 初始化、三角化、P3P/PnP、几何与鲁棒位姿计算 |
| src/map_store.cpp | 地图持久化、版本/CRC、固定锚点与读入校验 |
| src/formats.cpp | CSV 轮转和轨迹；无效位姿的矩阵字段留空 |
| src/ui.cpp / include/zslam/ui.hpp | 灰度与特征点、三维点云、轨迹/视锥和状态 UI |
| rtl/video/ | HDMI_2 扫描、TMDS 编码/串行器、管脚/CDC 约束 |
| vendor/orb_engine/ | 配对 ORB 用户态 C 引擎，保留来源哈希 |
| vendor/opencv_p3p/ | OpenCV 4.2.0 BSD 数值子集；ARM 无完整 OpenCV 运行时依赖 |
| vendor/jpeg_turbo/ | 固定 libjpeg-turbo 3.2.0 源码、来源与许可证 |
| tools/s1_reset_bridge.c | S1 独占读取、去抖、FIFO reset 和状态文件 |
| tools/capture_affinity.c | 严格限定当前候选进程的采集线程 CPU 掩码设置 |
| scripts/run_camera_s1.sh | 持续摄像头控制器；不回退录像，不自动重启故障 DMA |
| tools/calibrate_usb_camera.py | PC 棋盘拟合、拒绝/质量门槛和原图坐标还原 |
| tests/test_slam.cpp / tests/test_camera_calibration.py | 本机/ARM C++ 自检与 PC 标定回归 |
| interfaces/video_port.h / INTEGRATION.md | 帧与特征 ABI、视频集成接口 |

PL ORB 本体由保留的 HLS 导出 IP ZIP 提供。源 HLS 导出版本为 2024.2；当前已使用其导出 RTL 在 Vivado 2018.3 完成实现，未证明原 HLS C++ 能在 2018.3 HLS 中重新生成。配对 IP/Tcl 位于包内同名 retained handoff 子目录，不能用其他版本 IP 替代后沿用旧验收。

## 内存与地址

| 用途 | 地址 / 限制 |
|---|---|
| UIO map0 | 0x43c00000，64KiB；ORB 控制下半区，HDMI +0x8000 |
| UIO map1 | 0x43c10000，64KiB；描述子 |
| UIO map2 | 0x20000000，16MiB；同一 WC 共享映射，provider 版本 wc1 |
| ORB RX 槽 | 0x20800000 / 0x20900000 / 0x20a00000，间隔 1MiB |
| HDMI RGB565 槽 | 0x20b00000 / 0x20d00000，间隔 2MiB |

UIO 只允许一个持有共享 DDR 的实例，禁止增加第二种缓存属性的别名或让另一应用同时使用 DMA。UI 缓冲必须等切换确认后才可复用。原 DT 预留 0x20000000 起 512MiB no-map；具体 ABI 仍以配对代码/DT 和接口文档为准。

运行边界是 3000 地图点、16 关键帧、10 灰度帧池、容量各 2 的流水队列、CSV 每段 3600 行保留 3 段。S1 清图/清轨迹，不关闭摄像头、不改变标定。

无地图时 INITIALIZING；已有地图但位姿验证/重定位失败时 LOST。LOST 的 pose_valid=false，禁止复用旧成功位姿冒充本帧定位。现实现不会在长期 LOST 后自动建立 Atlas/新子图。绿色点是每帧独立 ORB 角点，不是持久跟踪 ID；地图为稀疏结构，单目尺度为相对单位。
