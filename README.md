# FPGA ORB 加速与双模式视觉建图定位系统

比赛工程的公开源码快照，更新于 2026-10-30。Zynq XC7Z015 的 PL 提取 ORB 特征，联合 RK3588 建图；地图交接后由 Zynq PS 在固定地图上定位。

## 两种运行模式

1. 联合建图：USB / 视频输入 → Zynq PS 准备灰度图 → PL ORB → 网络桥接 → RK3588 ORB-SLAM3 → 导出地图。
2. 本地定位：输入 → PL ORB → Zynq PS 地图匹配与 PnP → HDMI 图像和轨迹显示。

稠密点云用于环境显示；稀疏地图用于定位。匹配、几何估计和地图优化运行在处理器上，PL 加速 ORB 前端。

## 阅读源码的起点

| 部分 | 路径 | 内容 |
| --- | --- | --- |
| Zynq PS 主程序 | `zynq7015_demo/src/demo_main.cpp` | 比赛桥接与双模式应用入口 |
| PS 定位 | `zynq7015_demo/src/slam.cpp`, `pnp.cpp`, `map_store.cpp` | 匹配、位姿求解、地图管理 |
| PS 调度与显示 | `zynq7015_demo/include/zslam/pipeline.hpp`, `src/ui.cpp` | 帧缓冲所有权、流水和显示 |
| PL 算法 | `orb60/optimized/FPGA_ORB_HLS/fastv2/next/src/` | 图像流水、描述子等自定义 HLS 源码 |
| PL 系统连接 | `orb60/vivado/`, `zynq7015_demo/rtl/` | PS7/AXI/时钟复位、显示 RTL 与集成脚本 |
| 冻结 PL 发布输入 | `zynq7015_localization_handoff_20261022/` | 已保存的 HLS 输入与导出 IP，区别于实验候选 |
| RK ORB-SLAM3 | `rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3/` | 本地完整源码、第三方源码和许可证 |
| 跨板协议及地图交接 | `orb60/demo_bridge/`, `orb60/linux/` | 特征传输、建图接入、地图交接、构建部署 |
| RK 图形界面 | `orb60/viewer/` | Qt / EGL / GPU 显示 |
| 稠密重建 | `orb60/dense/` | 深度、NPU 调用和点云处理，模型权重未包含 |
| 开发说明 | `README_FIRST_ZH.md`, `DEVELOPMENT_GUIDE.md` | 构建入口、工具条件及历史版本边界 |

## 版本范围

- 原工程相对目录保持不变；这是一份源码快照，未导入私人本地 Git 历史。
- RK3588 当前无法连接，本仓库的 RK 部分来自电脑本地副本，未确认板上是否另有未同步修改。
- `baseline` 是历史参考，`next` 下有候选代码；不能把目录名称或当前工作树等同于已验收固件。配套冻结目录保留原始发布输入。
- 历史文档内的工具路径和实验指标对应各自版本，移植时需重新配置和验证。不同集成范围、工具版本的资源和时序不可混用。
- 本次公开发布只检查文件完整性和敏感内容，不代表重新完成构建或上板验收。

## 构建与依赖

先阅读 [交接说明](README_FIRST_ZH.md)。PS 使用 C++17 与 ARM hard-float 工具链；PL 保留 Vivado/Vitis HLS 2024.2 和复用导出 RTL 的 2018.3 路径；RK 构建与依赖见 `rk3588/orbslam3_cpu_baseline/README.md`。本机路径和板地址自行配置。

工具缓存、系统镜像、视频/大型测试数据、NPU 权重、SSH 私钥、本机配置不公开。保留已有第三方许可证、版权说明与源码；未给整个仓库额外套用统一许可证，各部分使用条件以其 LICENSE / NOTICE 为准。

网页端 AI 可从本 README 开始，按目录读取具体源码。大型词典与 IP ZIP 是配套输入，不是可直接浏览的源文件。
