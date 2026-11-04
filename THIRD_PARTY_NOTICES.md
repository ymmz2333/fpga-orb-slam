# 第三方来源与归属

所有第三方版权声明保留原样。团队贡献是 ORB 硬件架构、实现优化、板间接口、
固定地图定位应用、点投影核、调度和整机集成，不包括下列算法/库的原始发明。

| 组件 | 来源及许可 | 本仓库位置 |
|---|---|---|
| ORB-SLAM3 及 PS 适配 | https://github.com/UZ-SLAMLab/ORB_SLAM3 · GPLv3 | `review/kv260_slam_base/LICENSE`；`rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3/LICENSE` |
| ORB 参考表与定点参考 | ORB-SLAM3/OpenCV；GPL 与原 Willow Garage BSD 声明 | `orb60/optimized/FPGA_ORB_SHARED_v1.0/NOTICE.md`、`constants.hpp`；`frozen_pl_metadata/LICENSES/` |
| ZYNQ-7015 历史交接代码 | 工程中原始冻结交接来源；GPL-3.0-or-later | `zynq7015_demo/LICENSE`、`vendor/orb_engine/NOTICE.md` 及 provenance |
| DBoW2 | [ORB-SLAM 随附版本](https://github.com/raulmur/ORB_SLAM2/blob/master/Thirdparty/DBoW2/LICENSE.txt) · BSD-3-Clause | `LICENSES/DBoW2-ORB-SLAM-BSD.txt`；各 `Thirdparty/DBoW2/LICENSE.txt` |
| DUtils（Random/Timestamp） | ORB-SLAM 随附 DUtils 版本 · BSD-3-Clause | `LICENSES/DBoW2-ORB-SLAM-BSD.txt`；各 `Thirdparty/DBoW2/LICENSE.txt` |
| g2o | ORB-SLAM3 随附版本；按文件保留 BSD 等原条款 | `Thirdparty/g2o/license-bsd.txt` 和文件头 |
| Sophus | ORB-SLAM3 随附版本；MIT | `Thirdparty/Sophus/LICENSE.txt` |
| OpenCV P3P | https://github.com/opencv/opencv · 保留版本的 BSD-3-Clause | `zynq7015_demo/vendor/opencv_p3p/LICENSE` |
| libjpeg-turbo 及附属源文件 | https://github.com/libjpeg-turbo/libjpeg-turbo · IJG/BSD/zlib 及子组件原条款 | `zynq7015_demo/vendor/jpeg_turbo/upstream/LICENSE.md` 及子目录声明 |
| MiDaS v2.1 Small | https://github.com/isl-org/MiDaS · MIT | `LICENSES/MiDaS-MIT.txt`；`assets/models/` 中的微调权重与部署模型 |
| FastDepth（历史候选） | https://github.com/dwofk/fast-depth · MIT | `LICENSES/FastDepth-MIT.txt`；`orb60/dense/kv260/fastdepth/` |

外部运行依赖还包括 NumPy、OpenCV、PyTorch/torchvision、ONNX Runtime、
Eigen、Boost、OpenSSL、Qt/PyQt、Mesa/板载 Mali GLES、VART/XIR/XRT 等。
本仓库不打包这些工具的安装环境，其许可与版本要求见各发布方。
