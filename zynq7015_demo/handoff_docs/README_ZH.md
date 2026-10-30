# Zynq7015 USB 三维建图与定位源码交接

交接日期：2026-10-24。请先读本文，再读 docs/ 下的四份说明。

当前交接的是 **USB 实拍链路和轻量稀疏单目 SLAM 的开发版本**。摄像头采集、PS MJPEG 灰度解码、PL ORB、HDMI_2 显示及 S1 重置已经运行验证；**实拍频繁 LOST 尚未解决，持续整机 30FPS 未验收通过**。原 RK3588 完整 ORB-SLAM3 后端源码不在原始交付资料中，当前实现不能描述为它的完整等效移植。

```text
USB_HOST1 摄像头 1280×720 MJPEG / 30Hz
  → PS Linux V4L2 → libjpeg-turbo 灰度解码
  → 中心裁剪 960×720（x=160，不缩放）→ DDR
  → PL ORB（150MHz）→ PS 匹配 / 位姿 / 稀疏建图 / UI
  → DDR RGB565 双缓冲 → PL HDMI_2 1280×720 / 60Hz
S1（PS_MIO47 / KEY_UP103）→ evdev/FIFO → 清空地图和轨迹，继续摄像头
```

| 目录 / 文件 | 用途 |
|---|---|
| source/ | 当前源代码、RTL/XDC、测试、构建和标定工具、第三方源码及许可证 |
| artifacts/camera_runtime/ | 已核对的 ARM 主程序、自检程序、S1 工具及本相机标定；原部署包清单保留 |
| artifacts/fpga/ | 已验收 bit/HDF、布线 DCP 和报告；不自动加载到板卡 |
| artifacts/uvc/ | 与指定出厂内核匹配的临时 UVC/VMALLOC 模块及 CRC 证据 |
| artifacts/recovery/ | 原 SD 发布包、原 SD 文件备份和冻结基线清单，仅作恢复参考 |
| zynq7015_localization_handoff_20261022/ | 构建所需的配对 HLS 导出 IP/Tcl 和 WC 驱动来源子集；不是原交接包全部内容 |
| dependencies/ | 出厂 Linux 源码包、固定版本离线依赖、主机隔离工具链配置参考 |
| evidence/ | 构建/自检、真实标定、实拍、黄金回归、S1 及历史断点证据 |
| manifest.json / SHA256SUMS | 包内容、验证关系与逐文件 SHA-256 |
| verify_handoff.py | 只读核对本包及源码与既有产物的对应关系；不会编译、连接或配置板卡 |

先执行 `python verify_handoff.py`。应输出 `PASS_HANDOFF_INTEGRITY`。它确认文件完整和历史构建输入对应，**不等于重新运行了编译、仿真或板测**。脚本需要 Python 3.10+；建议使用 3.11/3.12。

主程序固定版本为 `arm_20261024_180124`，S1 工具为 `s1_controls_20261024_192801`，配套 PL 为 `final_20261023_201146`。软件默认目标 30FPS；历史源目录名 zynq_slam_60fps 和部分旧说明保留，不表示已实现 60FPS。

**以本包 source/ 为当前源码入口。** artifacts/camera_runtime/source.tar.gz 和该目录旧 README/manifest 是最初部署包的历史记录，保留用于验证原 SHA；其中不包含后来补齐的 PC 标定/S1 交接工作，不应作为当前源码替代品。

## 接手顺序

1. 阅读 [状态与未完成工作](docs/STATUS_AND_NEXT_ZH.md)，区分录像回归与实拍结果。
2. 阅读 [代码与接口](docs/SOURCE_MAP_ZH.md)，确认 PS/PL 边界及内存布局。
3. 按 [构建与核验](docs/BUILD_AND_VERIFY_ZH.md) 配置主机，先本机自检再 ARM 构建。
4. 按 [板端交接](docs/BOARD_HANDOVER_ZH.md) 只读检查设备，再决定是否运行。不要直接执行历史录像基准脚本。

本次整理仅复制、归档和核对本地文件，没有综合、重新编译、重启板卡、切换显示或更改 SD。整理前的实时测试未完成：曾查到 aTrust VPN 路由截走板卡地址；随后物理网口已断开，无法确认板卡当前运行状态。19:58 的进程号仅为历史记录，不能据此操作当前进程。

大型原始回归数据 `gray8.bin`（1,571,097,600 字节）及其完整黄金数据没有重复装入本包。其已有本机/板端位置和已知归档 SHA 见 manifest.json 的 external_datasets。执行完整 2273 帧回归前，仍需取回并核对这些数据；内置小样本足以进行源码自检。

请保留全部第三方许可证和 provenance。Vivado/SDK、MinGW、Python 安装环境不随包分发；离线依赖包不替代这些工具的安装或许可。
