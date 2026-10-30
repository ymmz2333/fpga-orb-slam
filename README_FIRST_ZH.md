# FPGA ORB 比赛项目源码交接 — 2026-10-30

本包保留原项目相对目录。解压后的 FPGA_ORB_TEAM_SOURCE_20261030 是工程根目录。

## 三端入口
- PS：zynq7015_demo/src/demo_main.cpp；src/slam.cpp、src/ui.cpp；include/zslam；vendor/orb_engine。比赛桥接应用以 demo_main.cpp 为入口，src/main.cpp 为独立应用入口。
- PL：orb60/optimized/FPGA_ORB_HLS/fastv2（HLS C++/PS/host）；orb60/optimized/FPGA_ORB_SHARED_v1.0；orb60/vivado（2024.2 Tcl）；zynq7015_demo/rtl 和 scripts（HDMI / 2018.3 集成）。baseline 为历史参考，next 为候选实现，不能自动当作已验收发布版。
- 配套冻结 PL：zynq7015_localization_handoff_20261022/.../fpga_baseline，含两个已导出 IP ZIP、对应输入源码与 top_inputs。供迁移脚本复用，不要直接修改导出 RTL。HDMI 完整顶层使用 PS 工程中的 RTL/脚本。
- RK3588：rk3588/orbslam3_cpu_baseline/vendor/ORB_SLAM3 为完整本地 ORB-SLAM3 源码，含 Thirdparty、LICENSE、词典压缩包；同级 scripts、patches、configs、demo 为构建和实验入口。
- 联合建图/地图交接：orb60/demo_bridge（尤其 rk 子目录）、orb60/linux。
- RK GUI：orb60/viewer；稠密重建：orb60/dense（含 NPU 调用和 SLAM 适配代码）。模型权重不在本源码包中。

## 构建说明
1. 先阅读 START_HERE.md、DEVELOPMENT_GUIDE.md，复制 scripts/local_env.example.ps1 为本机 local_env.ps1；工具安装路径需按本机配置，不能直接使用历史文档中的用户路径。
2. PS/桥接构建：python3 -m orb60.demo_bridge.build_arm --compiler /usr/bin/arm-linux-gnueabihf-g++-9 --jpeg-library orb60/demo_bridge/dependencies/libturbojpeg-arm.a --fully-static --with-selftests --output build/arm
   Windows 快速构建入口：orb60/demo_bridge/build_native.py。静态 JPEG 库与 vendor 源码一并保留。
3. RK 构建：阅读 rk3588/orbslam3_cpu_baseline/README.md、docs/B1_RUNBOOK.md 和 scripts/common.sh；build_orbslam3.sh 构建现有 vendor 源码。build_a1.sh 是历史完整获取/打补丁流程，不能直接在现有修改树重复套补丁。
4. RK GUI：orb60/demo_bridge/requirements-rk-gui.txt；GPU 入口及自启动脚本在 demo_bridge/rk 下，viewer 中 EGL/FBO 后端为本次报告对应路径。
5. PL：阅读 zynq7015_demo/PL_BUILD_ZH.md 与 HDMI_IMPLEMENTATION_ZH.md；2024.2 HLS 和 2018.3 复用导出 RTL 两条路径分开保留。2018.3 脚本含原交接机器的工具启动器路径，需要为队友机器适配；本次不改写历史源码或声称从干净机器可一键构建。

## 快照范围与限制
- 来源是 D:/pld 中本地工作树，不仅限 Git 已提交文件。SHA256SUMS.json 列出包内每个源码文件的哈希和字节数。
- 本次尝试连接 RK3588，SSH 别名指向的 lubancat.local 无法解析，因此 RK 文件是电脑上的本地快照，未声称是板上当前工作树的实时同步副本。
- 未包含 SSH 私钥、本机 local_board.json/local_env.ps1、Python 虚拟环境、视频/大数据集、NPU 权重、Vivado 工作缓存、bitstream/BOOT/内核镜像。第三方依赖源码、许可证与 ORB 词典保留；OpenCV/Pangolin 等按 RK 脚本获取和构建。
- 本次只核验打包完整性，没有启动综合、编译、烧写或板端实验；历史文档中的性能和通过状态保留原日期与范围。
- 解压后运行 python verify_package.py 核验 SHA256；该检查只证明文件完整，不代替构建和上板验证。
