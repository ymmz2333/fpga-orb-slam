# 开源许可范围

本项目按 GPL-3.0-or-later 发布团队代码和 ORB-SLAM3 衍生集成，完整条款见根目录 `LICENSE`。
版权归原作者及相应贡献者所有，保留各文件的原版权声明。

本项目包含 ORB-SLAM3、ORB 提取参考表及衍生接口。ORB-SLAM3 上游采用 GPLv3，
项目中已有的 `zynq7015_demo/LICENSE`、共享参考包及 NOTICE 也保留 GPL 许可。
因此本次不会用一份 MIT/Apache-2.0 文本覆盖整个工程。

独立第三方组件继续采用各自许可，包括 MiDaS/FastDepth 的 MIT、
DBoW2/DUtils 和 OpenCV 相关部分的 BSD、Sophus 的 MIT，以及 JPEG 组件原许可。
第三方逐项来源见 `THIRD_PARTY_NOTICES.md`。聚合分发不改变这些组件的版权或原许可。

可按适用协议复制、修改和再分发。再分发时保留许可证、版权与归属声明；
分发受 GPL 覆盖的修改版本或可执行程序时，按 GPL 提供相应源码和修改说明。
没有提供适用协议以外的商标、专利、硬件工具或数据集权利。

AMD Vivado/Vitis、DPU 厂商 IP、板卡 BSP、操作系统和驱动需从其发布方取得，
按各自许可使用。本仓库提供团队编写的 HLS、RTL、Tcl、配置和软件适配，
不重新分发 AMD 加密 IP、工具安装包、第三方专有库或系统镜像。

团队：芯火启航；成员：王纪新、李子阳、孙诗宁；提交队伍编号：53996。
