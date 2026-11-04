# 环境、依赖与模型资产

| 部分 | 环境与依赖 |
|---|---|
| 电脑脚本/测试 | CPython 3.12；pytest、NumPy、OpenCV、Pillow；按相关模块安装额外依赖 |
| ZYNQ-7015 硬件 | XC7Z015CLG485-2；冻结 HDMI 集成 Vivado 2018.3；ORB 开发 HLS/Vivado 2024.2 按所选入口使用 |
| ZYNQ-7015 PS | ARM32 Linux hard-float；C++17；libjpeg-turbo 3.2.0；工程中冻结的头文件与库接口 |
| KV260 PS | Kria Ubuntu 22.04 ARM64；CMake、GCC、OpenCV>=4.4、Eigen3>=3.3、Boost serialization、OpenSSL、pthread |
| KV260 图形界面 | Qt/PyQt5、板载 Mali GLES2/EGL 驱动；图形会话需处于实际登录状态 |
| KV260 DPU | Vitis AI 2.5、VART/XIR、匹配驱动与平台；DPUCZDX8G ISA1 B4096 |
| KV260 PL | Vivado/Vitis HLS 2024.2；K26 part `xck26-sfvc784-2LV-c`；官方 DPU IP 与 KV260 board files |

## 模型文件

`assets/models/midas_qat_best.pth` 是本项目保存的 MiDaS Small QAT 微调状态，
`midas_kv260_b4096.xmodel` 是对应已编译部署模型。
源权重、部署文件大小和 SHA-256 在 `assets/models/MANIFEST.json`。
模型及其微调来源保留 MiDaS MIT 许可，见 `LICENSES/MiDaS-MIT.txt`。

部署 xmodel 指纹为 `0x101000016010407`，外部接口为 RGB/ImageNet 归一化输入、
256×256 float32 相对逆深度输出，具体内部子图与 PS 运算清单见 `placement.json`。
该模型的视觉效果接受记录与原数值阈值结果分别保留于原报告，不能将视觉接受改写为
原 3% NRMSE / 0.98 Spearman 门槛通过。

`orb60/dense/kv260/midas_refine/README.md` 与 `qat_model.py`、`qat_train.py`、
`video_test.py` 记录模型构造、量化训练和参考推理入口。
Vitis AI 编译入口为 `compile_model.py`。运行 DPU 前须实际核对硬件指纹和当前启动回执。

ORB 词典保留于 `rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3/Vocabulary/ORBvoc.txt.tar.gz`，
可解压为运行时词典；目录名是历史来源，当前系统无需 RK3588 板卡。

## 代码包包含什么

包含 HLS/C/C++/RTL、PS 软件、Python 控制、Tcl/PowerShell/设备树/约束、
测试和参考模型、第三方开源源码、保留编译输入、许可及模型资产。
文件哈希由根目录 `SOURCE_SNAPSHOT_SHA256.json` 给出。

不包含第三方工具安装包、AMD 加密 IP、操作系统镜像、生成的 Vivado/HLS 缓存、
旧数据集时间戳列表、录像和私人认证材料。外部库按发布方许可安装。
板卡网络、相机标定、UIO 序号、驱动与显示参数需按实际设备配置。
